"""Owner-only AWS ops mode: who can use it, Yes-before-act, single use, and what is never possible."""
import json
import time

import pytest
from botocore.exceptions import ClientError

import kavach_common as kc
import kavach_ops as kops
import main
import ops
from kavach_context import start_request
from tools import ops as ops_tools

OWNER = "+919121095635"
STRANGER = "+919800000001"


class FakeEC2:
    def __init__(self, instances):
        self.instances, self.calls = instances, []

    def get_paginator(self, _name):
        fake = self

        class Pager:
            def paginate(self, InstanceIds=None):
                found = [i for i in fake.instances if not InstanceIds or i["InstanceId"] in InstanceIds]
                if InstanceIds and not found:
                    raise ClientError({"Error": {"Code": "InvalidInstanceID.NotFound"}}, "DescribeInstances")
                return [{"Reservations": [{"Instances": found}]}]
        return Pager()

    def _act(self, name, ids, state):
        self.calls.append((name, ids))
        for i in self.instances:
            if i["InstanceId"] in ids:
                i["State"]["Name"] = state

    def stop_instances(self, InstanceIds):
        self._act("stop", InstanceIds, "stopping")

    def start_instances(self, InstanceIds):
        self._act("start", InstanceIds, "pending")

    def reboot_instances(self, InstanceIds):
        self._act("reboot", InstanceIds, "running")

    def list_functions(self):
        return {"Functions": [{"FunctionName": "kavach-inbound"}], "ResponseMetadata": {}}


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["message_id"]] = dict(Item)

    def delete_item(self, Key, ConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues, ReturnValues):
        item = self.items.get(Key["message_id"])
        if not item or item.get("kind") != ExpressionAttributeValues[":kind"] \
                or item.get("phone") != ExpressionAttributeValues[":phone"]:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "DeleteItem")
        del self.items[Key["message_id"]]
        return {"Attributes": item}


def _instance(iid, name, state):
    return {"InstanceId": iid, "InstanceType": "t3.micro", "State": {"Name": state},
            "Tags": [{"Key": "Name", "Value": name}], "PublicIpAddress": "13.0.0.1"}


@pytest.fixture
def aws(monkeypatch):
    mumbai = FakeEC2([_instance("i-0aaaaaaaaaaaaaaa1", "dev-server", "running"),
                      _instance("i-0aaaaaaaaaaaaaaa2", "dev-server-2", "stopped"),
                      _instance("i-0aaaaaaaaaaaaaaa3", "old-box", "terminated")])
    virginia = FakeEC2([_instance("i-0bbbbbbbbbbbbbbb1", "website", "running")])
    table = FakeTable()
    monkeypatch.setattr(kc, "cfg", lambda: {"ops_owner_phones": f"{OWNER}, +91 98000 00009",
                                            "ops_regions": "ap-south-1,us-east-1", "region": "ap-south-1"})
    monkeypatch.setattr(kc, "client", lambda name, region=None: {"ap-south-1": mumbai, "us-east-1": virginia}[region or "ap-south-1"])
    monkeypatch.setattr(kc, "table", lambda key: table)
    return {"mumbai": mumbai, "virginia": virginia, "table": table}


def test_only_owner_typed_aws_messages_are_ops(aws):
    assert kops.ops_command("aws list my instances", OWNER) == "list my instances"
    assert kops.ops_command("AWS: stop dev-server", "9121095635") == "stop dev-server"
    assert kops.ops_command("ops", OWNER) == "What can you do?"
    assert kops.ops_command("aws list my instances", STRANGER) is None
    assert kops.ops_command("AWS account suspended, verify now", OWNER, forwarded=True) is None
    assert kops.ops_command("awesome, thanks", OWNER) is None
    assert kops.is_owner("+919800000009")


def test_ops_is_off_without_config(monkeypatch):
    assert kops.ops_command("aws list", OWNER) is None  # conftest: no config at all


def test_find_instances_across_regions(aws):
    names = {i["name"]: i["region"] for i in kops.find_instances()}
    assert names == {"dev-server": "ap-south-1", "dev-server-2": "ap-south-1", "website": "us-east-1"}
    inst, candidates = kops.pick_instance("dev-server")
    assert inst["id"] == "i-0aaaaaaaaaaaaaaa1" and len(candidates) == 2  # exact name beats partial
    assert kops.pick_instance("i-0bbbbbbbbbbbbbbb1")[0]["name"] == "website"
    assert kops.pick_instance("server")[0] is None  # ambiguous


def test_stop_needs_yes_and_runs_once(aws):
    req = start_request(user={"phone": OWNER})
    out = json.loads(ops_tools.request_instance_action("dev-server", "stop"))
    assert out["pending_confirmation"] and aws["mumbai"].calls == []  # nothing happened yet
    token = req.ops_pending["token"]
    assert "Stop *dev-server*" in req.ops_pending["question"]
    assert kops.confirm_buttons(token)[0]["id"] == f"OPS|yes|{token}"

    assert kops.handle_tap(STRANGER, "yes", token) == "Only the Kavach owner can do this."
    reply = kops.handle_tap(OWNER, "yes", token)
    assert reply.startswith("✅ Stopping *dev-server*") and "stopping" in reply
    assert aws["mumbai"].calls == [("stop", ["i-0aaaaaaaaaaaaaaa1"])]
    assert "already handled" in kops.handle_tap(OWNER, "yes", token)
    assert len(aws["mumbai"].calls) == 1


def test_cancel_and_expiry(aws):
    inst = kops.find_instances("website")[0]
    token = kops.create_pending(OWNER, "stop", inst)["token"]
    assert kops.handle_tap(OWNER, "no", token).startswith("Cancelled")
    token = kops.create_pending(OWNER, "stop", inst)["token"]
    aws["table"].items[f"ops-{token}"]["expires_at"] = int(time.time()) - 1
    assert "expired" in kops.handle_tap(OWNER, "yes", token)
    assert aws["virginia"].calls == []


def test_one_action_per_message_and_state_checks(aws):
    req = start_request(user={"phone": OWNER})
    assert "can't be started" in ops_tools.request_instance_action("dev-server", "start")
    assert "No single instance" in ops_tools.request_instance_action("server", "stop")
    assert json.loads(ops_tools.request_instance_action("dev-server-2", "start"))["pending_confirmation"]
    assert "Only one action" in ops_tools.request_instance_action("website", "stop")
    assert req.ops_pending["action"] == "start"


def test_destructive_and_secret_calls_are_refused(aws):
    start_request(user={"phone": OWNER})
    assert "only start, stop or reboot" in ops_tools.request_instance_action("dev-server", "terminate")
    assert "not allowed" in ops_tools.aws_read("ec2", "terminate_instances")
    assert "not allowed" in ops_tools.aws_read("s3", "get_object", {"Bucket": "b", "Key": "k"})
    assert "not allowed" in ops_tools.aws_read("ec2", "describe_instance_attribute")
    assert "not available" in ops_tools.aws_read("secretsmanager", "get_secret_value")
    assert "not available" in ops_tools.aws_read("iam", "list_users")
    ok = json.loads(ops_tools.aws_read("lambda", "list_functions"))
    assert ok == {"Functions": [{"FunctionName": "kavach-inbound"}]}


# ----------------------------------------------------------------------------- agent and Lambda wiring

class FakeOpsAgent:
    def __init__(self, act=None):
        self.act, self.prompts = act, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.act:
            self.act()
        return "**Stop dev-server?** Tap Yes to go ahead."


def test_agent_ops_mode_returns_yes_cancel_buttons(aws, monkeypatch):
    monkeypatch.setattr(ops, "get_session_manager", lambda *_a: None)
    agent = FakeOpsAgent(lambda: ops_tools.request_instance_action("dev-server", "stop"))
    monkeypatch.setattr(ops, "make_ops_agent", lambda _sm: agent)
    out = main.invoke({"mode": "ops", "prompt": "stop dev-server", "user": {"phone": OWNER}})
    assert out["reply"] == "*Stop dev-server?* Tap Yes to go ahead."
    assert [b["title"] for b in out["buttons"]] == ["Yes, do it", "Cancel"]
    assert out["buttons"][0]["id"].startswith("OPS|yes|") and "Stop *dev-server*" in out["buttons_text"]
    assert aws["mumbai"].calls == []


def test_agent_refuses_ops_for_non_owner(aws, monkeypatch):
    monkeypatch.setattr(ops, "make_ops_agent", lambda _sm: pytest.fail("agent must not run"))
    out = main.invoke({"mode": "ops", "prompt": "list instances", "user": {"phone": STRANGER}})
    assert "only available to the Kavach owner" in out["reply"] and out["buttons"] == []


@pytest.fixture
def lambda_app(aws, monkeypatch):
    import app

    sent = {"text": [], "agent": [], "buttons": []}
    monkeypatch.setattr(app, "_first_time_seen", lambda _m: True)
    monkeypatch.setattr(app.kc, "wa_mark_read", lambda _m: None)
    monkeypatch.setattr(app.kc, "get_user", lambda p: {"phone": kc.normalize_phone(p), "status": "active",
                                                       "language": "en", "guardians": []})
    monkeypatch.setattr(app.kc, "wa_text", lambda to, body: sent["text"].append(body))
    monkeypatch.setattr(app.kc, "wa_buttons", lambda to, body, buttons: sent["buttons"].append(buttons))
    monkeypatch.setattr(app, "call_agent", lambda user, prompt, media, mid, mode=None:
                        sent["agent"].append((prompt, mode)) or {"reply": "done", "buttons": []})
    return app, sent


def _text_message(sender, body, forwarded=False):
    msg = {"id": f"wamid.{time.time()}", "from": sender.lstrip("+"), "type": "text", "text": {"body": body}}
    if forwarded:
        msg["context"] = {"forwarded": True}
    return msg


def test_lambda_sends_owner_aws_messages_to_ops(lambda_app):
    app, sent = lambda_app
    app.process_message(_text_message(OWNER, "aws which instances are running?"), None)
    assert sent["agent"] == [("which instances are running?", "ops")]
    assert sent["text"][0] == "⚙️ On it…"


def test_lambda_keeps_scam_checks_for_everything_else(lambda_app):
    app, sent = lambda_app
    app.process_message(_text_message(OWNER, "AWS account suspended, verify at aws-verify.top", forwarded=True), None)
    app.process_message(_text_message(STRANGER, "aws list instances"), None)
    assert [mode for _p, mode in sent["agent"]] == [None, None]


def test_lambda_runs_ops_tap(lambda_app, monkeypatch):
    app, sent = lambda_app
    taps = []
    monkeypatch.setattr(app.kops, "handle_tap", lambda phone, answer, token: taps.append((phone, answer, token)) or "✅")
    app.handle_choice(OWNER, {"phone": OWNER}, None, "OPS|yes|abc123")
    assert taps == [(OWNER, "yes", "abc123")] and sent["text"] == ["✅"]
