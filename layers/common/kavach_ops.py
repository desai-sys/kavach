"""Owner-only AWS ops mode: run your AWS account from WhatsApp, safely.

The person who runs Kavach (the owner) can message the Kavach number from an allow-listed phone:
    aws which instances are running?
    aws how much have I spent this month?
    aws are my WhatsApp templates approved?
    aws stop the dev-server instance

Anything that isn't an "aws ..." / "ops ..." message, and anything forwarded, still goes to the normal scam
check, so the owner can use both.

Safety design:
  * Only numbers in the ops_owner_phones setting can use it (checked in the Lambda and again in the agent).
  * The ops agent (agent/ops.py) has view-only permissions. It can only REQUEST start / stop / reboot of
    an EC2 instance; Kavach then shows Yes / Cancel buttons and this module runs the action in the inbound
    Lambda when the owner taps Yes. Requests are single-use and expire after 10 minutes.
  * Terminate, delete, security-group and IAM changes are impossible: no Kavach role has those permissions.
"""
from __future__ import annotations

import re
import time
import uuid

from botocore.exceptions import ClientError

import kavach_common as kc

OPS_PREFIX = re.compile(r"^\s*(aws|ops)\b[\s:,.-]*(.*)$", re.I | re.S)
ACTIONS = {"start": ("start_instances", "Starting"),
           "stop": ("stop_instances", "Stopping"),
           "reboot": ("reboot_instances", "Rebooting")}
ALLOWED_FROM_STATE = {"start": {"stopped"}, "stop": {"running"}, "reboot": {"running"}}
CONFIRM_MINUTES = 10


def owners() -> set[str]:
    raw = str(kc.cfg().get("ops_owner_phones") or "")
    return {kc.normalize_phone(p) for p in re.split(r"[,;]+", raw) if p.strip()}  # "+91 98..." may have spaces


def is_owner(phone: str) -> bool:
    try:
        return bool(phone) and kc.normalize_phone(phone) in owners()
    except Exception as exc:  # no config: ops mode is simply off
        print(f"Ops owner check failed: {exc!r}")
        return False


def ops_command(text: str | None, phone: str, forwarded: bool = False) -> str | None:
    """The request if this message is an ops command from an owner ("aws ..." or "ops ..."), else None."""
    if forwarded or not text:
        return None
    m = OPS_PREFIX.match(text)
    if not m or not is_owner(phone):
        return None
    return m.group(2).strip() or "What can you do?"


def regions() -> list[str]:
    c = kc.cfg()
    raw = str(c.get("ops_regions") or c.get("region") or "ap-south-1")
    return [r for r in re.split(r"[,;\s]+", raw) if r]


# ----------------------------------------------------------------------------- instances

def _summary(inst: dict, region: str) -> dict:
    name = next((t["Value"] for t in inst.get("Tags", []) if t.get("Key") == "Name"), "")
    return {"id": inst["InstanceId"], "name": name, "state": inst.get("State", {}).get("Name", ""),
            "type": inst.get("InstanceType", ""), "region": region,
            "public_ip": inst.get("PublicIpAddress", ""), "private_ip": inst.get("PrivateIpAddress", ""),
            "launched": str(inst.get("LaunchTime", ""))[:16]}


def find_instances(query: str = "", region: str = "") -> list[dict]:
    """Non-terminated instances matching an instance id or part of the Name tag (all if query is empty)."""
    query = (query or "").strip()
    by_id = bool(re.fullmatch(r"i-[0-9a-f]{8,17}", query))
    found = []
    for r in ([region] if region else regions()):
        ec2 = kc.client("ec2", r)
        try:
            pages = ec2.get_paginator("describe_instances").paginate(**({"InstanceIds": [query]} if by_id else {}))
            for page in pages:
                for reservation in page.get("Reservations", []):
                    for inst in reservation.get("Instances", []):
                        s = _summary(inst, r)
                        if s["state"] in ("terminated", "shutting-down"):
                            continue
                        if query and not by_id and query.lower() not in s["name"].lower():
                            continue
                        found.append(s)
        except ClientError as exc:
            if "InvalidInstanceID" not in exc.response.get("Error", {}).get("Code", ""):
                raise
    return found


def pick_instance(query: str, region: str = "") -> tuple[dict | None, list[dict]]:
    """(the one instance meant, all candidates). Exact id or name wins over a partial name match."""
    matches = find_instances(query, region)
    exact = [m for m in matches if m["id"] == query or m["name"].lower() == (query or "").strip().lower()]
    if len(exact) == 1:
        return exact[0], matches
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


# ----------------------------------------------------------------------------- confirm, then act

def create_pending(phone: str, action: str, inst: dict) -> dict:
    """Store a single-use request that runs only when the owner taps Yes."""
    token = uuid.uuid4().hex[:16]
    kc.table("dedupe_table").put_item(Item=kc.clean_for_dynamo({
        "message_id": f"ops-{token}", "kind": "ops_pending", "phone": kc.normalize_phone(phone),
        "action": action, "instance_id": inst["id"], "instance_name": inst.get("name", ""),
        "region": inst["region"], "expires_at": int(time.time()) + CONFIRM_MINUTES * 60,
    }))
    label = f"*{inst['name']}* ({inst['id']})" if inst.get("name") else f"*{inst['id']}*"
    question = (f"{action.title()} {label} in {inst['region']}? It is {inst.get('state', 'unknown')} now. "
                f"Nothing happens until you tap Yes (expires in {CONFIRM_MINUTES} minutes).")
    return {"token": token, "question": question, "action": action, "instance": inst}


def confirm_buttons(token: str) -> list[dict]:
    return [{"id": f"OPS|yes|{token}", "title": "Yes, do it"}, {"id": f"OPS|no|{token}", "title": "Cancel"}]


def handle_tap(phone: str, answer: str, token: str) -> str:
    """Run (or cancel) a pending request. Single use: the request is deleted before anything runs."""
    phone = kc.normalize_phone(phone)
    if not is_owner(phone):
        return "Only the Kavach owner can do this."
    try:
        item = kc.table("dedupe_table").delete_item(
            Key={"message_id": f"ops-{token}"},
            ConditionExpression="attribute_exists(message_id) AND #k = :kind AND #p = :phone",
            ExpressionAttributeNames={"#k": "kind", "#p": "phone"},
            ExpressionAttributeValues={":kind": "ops_pending", ":phone": phone},
            ReturnValues="ALL_OLD",
        ).get("Attributes")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return "This request was already handled or has expired. Ask again if you still need it."
        raise
    item = kc.to_jsonable(item or {})
    if not item or int(item.get("expires_at", 0)) < time.time():
        return "This request has expired. Nothing was changed; ask again if you still need it."
    label = f"*{item.get('instance_name')}* ({item['instance_id']})" if item.get("instance_name") else f"*{item['instance_id']}*"
    if answer != "yes":
        return f"Cancelled. {label} was not changed."
    method, verb = ACTIONS[item["action"]]
    ec2 = kc.client("ec2", item["region"])
    try:
        getattr(ec2, method)(InstanceIds=[item["instance_id"]])
    except ClientError as exc:
        err = exc.response.get("Error", {})
        return f"❌ AWS refused to {item['action']} {label}: {err.get('Code')}: {err.get('Message', '')[:200]}"
    state = ""
    try:
        state = find_instances(item["instance_id"], item["region"])[0]["state"]
    except Exception:
        pass
    print(f"OPS {item['action']} {item['instance_id']} in {item['region']} approved by {phone}")
    return f"✅ {verb} {label} in {item['region']}." + (f" Current state: {state}." if state else "")
