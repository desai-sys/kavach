"""Swiggy food ordering: sign-in pieces, the confirm-before-order rule, and the cart checks."""
import base64
import hashlib
import importlib.util
import json
import time
import urllib.parse
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import food
import kavach_common as kc
import kavach_swiggy as ksw
import main
from kavach_context import current, start_request
from tools import everyday

PHONE = "+919121095635"
USER = {"phone": PHONE, "name": "Lakshmi Amma", "language": "en", "status": "active", "guardians": []}


class FakeDedupe:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, **_kw):
        self.items[Item["message_id"]] = dict(Item)

    def delete_item(self, Key, ConditionExpression=None, ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None, ReturnValues=None):
        item = self.items.get(Key["message_id"])
        vals = ExpressionAttributeValues or {}
        if not item or (":phone" in vals and (item.get("phone") != vals[":phone"] or item.get("kind") != vals[":kind"])):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "DeleteItem")
        del self.items[Key["message_id"]]
        return {"Attributes": item}


@pytest.fixture
def dedupe(monkeypatch):
    table = FakeDedupe()
    monkeypatch.setattr(kc, "table", lambda key: table)
    return table


# ----------------------------------------------------------------------------- sign-in

def test_pkce_and_authorize_url_follow_swiggys_docs():
    verifier, challenge = ksw.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = ksw.authorize_url("cid", "https://x.lambda-url.ap-south-1.on.aws/callback", challenge, "st8")
    assert url.startswith("https://mcp.swiggy.com/auth/authorize?")
    q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
    assert q == {"response_type": "code", "client_id": "cid", "redirect_uri": "https://x.lambda-url.ap-south-1.on.aws/callback",
                 "code_challenge": challenge, "code_challenge_method": "S256", "state": "st8", "scope": "mcp:tools"}


def test_swiggy_is_off_until_approved():
    assert not ksw.enabled()  # no config in tests


# ----------------------------------------------------------------------------- confirm before ordering

def test_order_request_is_single_use_and_owned(dedupe):
    pending = ksw.create_pending(PHONE, "addr-1", 238.0, "Sri Krishna Tiffins: 2 idli, 1 coffee")
    text, buttons = ksw.confirm_prompt(pending, "te")
    assert "₹238" in text and buttons[0]["id"] == f"FOOD|yes|{pending['token']}"
    assert all(len(b["title"]) <= 20 for b in buttons)
    with pytest.raises(ksw.NotLinked):
        ksw.take_pending("+919800000005", pending["token"])  # someone else's tap
    assert ksw.take_pending(PHONE, pending["token"])["address_id"] == "addr-1"
    with pytest.raises(ksw.NotLinked):
        ksw.take_pending(PHONE, pending["token"])  # second tap


def test_expired_order_request(dedupe):
    pending = ksw.create_pending(PHONE, "addr-1", 100.0, "x")
    dedupe.items[f"food-{pending['token']}"]["expires_at"] = int(time.time()) - 1
    with pytest.raises(ksw.NotLinked):
        ksw.take_pending(PHONE, pending["token"])


# ----------------------------------------------------------------------------- cart and placing

def test_total_and_result_parsing():
    assert food.find_total({"data": {"items": [{"price": 60}], "bill": {"toPay": 238}}}) == 238.0
    assert food.find_total({"cart": {"total": "₹1,050.00"}}) == 1050.0
    assert food.find_total("no cart") is None
    assert food.parse_result({"content": [{"text": json.dumps({"data": {"orderId": "123"}})}]}) == {"data": {"orderId": "123"}}
    assert food.parse_result({"structuredContent": {"a": 1}, "content": []}) == {"a": 1}


class FakeTool:
    def __init__(self, name, props=None):
        self.tool_name = name
        self.tool_spec = {"inputSchema": {"json": {"type": "object", "properties": props or {}}}}


class FakeClient:
    def __init__(self, total, place_props=None, place_result=None):
        self.total, self.calls = total, []
        self.place_props = place_props if place_props is not None else {"paymentMethod": {}, "addressId": {}}
        self.place_result = place_result or {"status": "success", "content": [{"text": json.dumps({"data": {"orderId": "SW-991"}})}]}

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def list_tools_sync(self):
        return [FakeTool(n) for n in sorted(food.MODEL_TOOLS)] + [FakeTool("place_food_order", self.place_props)]

    def call_tool_sync(self, tool_use_id, name, arguments=None):
        self.calls.append((name, arguments))
        if name == "get_food_cart":
            return {"status": "success", "content": [{"text": json.dumps({"data": {"total": self.total}})}]}
        if name == "place_food_order":
            return self.place_result
        return {"status": "success", "content": [{"text": "{}"}]}


def test_place_order_after_checking_the_cart():
    client = FakeClient(238)
    out = food.place_order(client, "addr-1", 238.0)
    assert out == {"placed": True, "order_id": "SW-991", "total": 238.0}
    assert client.calls[-1] == ("place_food_order", {"paymentMethod": "COD", "addressId": "addr-1"})


def test_place_order_sends_only_arguments_swiggy_accepts():
    client = FakeClient(238, place_props={"paymentMethod": {}})
    food.place_order(client, "addr-1", 238.0)
    assert client.calls[-1] == ("place_food_order", {"paymentMethod": "COD"})


def test_nothing_is_ordered_if_the_cart_changed_or_is_over_the_cap():
    changed = FakeClient(300)
    assert not food.place_order(changed, "addr-1", 238.0)["placed"]
    assert "place_food_order" not in [c[0] for c in changed.calls]
    over = FakeClient(1200)
    assert "₹1000" in food.place_order(over, "addr-1", None)["reason"]


def test_swiggy_error_is_reported_not_retried():
    client = FakeClient(238, place_result={"status": "error", "content": [{"text": "Restaurant is closed"}]})
    out = food.place_order(client, "addr-1", 238.0)
    assert out["placed"] is False and "closed" in out["reason"]
    assert [c[0] for c in client.calls].count("place_food_order") == 1


def test_model_cannot_place_orders():
    assert "place_food_order" not in food.MODEL_TOOLS and "confirm_order" not in food.MODEL_TOOLS


def test_confirmation_tool_checks_the_cap_and_waits_for_a_tap():
    pending = []
    food._run.update(client=FakeClient(238), on_confirm=lambda **kw: pending.append(kw) or kw, pending=None)
    out = json.loads(food.request_order_confirmation("addr-1", "Sri Krishna Tiffins: 2 idli"))
    assert out["pending_confirmation"] and pending[0]["total"] == 238.0
    assert "already waiting" in food.request_order_confirmation("addr-1", "again")
    food._run.update(client=FakeClient(1500), pending=None)
    assert "limits these orders" in food.request_order_confirmation("addr-1", "big order")


# ----------------------------------------------------------------------------- agent wiring

def test_order_food_tool_when_off_or_not_linked(monkeypatch):
    start_request(user=dict(USER))
    assert json.loads(everyday.order_food("2 idli"))["available"] is False
    monkeypatch.setattr(everyday.ksw, "enabled", lambda: True)

    def not_linked(_phone):
        raise ksw.NotLinked("No Swiggy account linked.")

    monkeypatch.setattr(everyday.ksw, "access_token", not_linked)
    assert "LINK SWIGGY" in json.loads(everyday.order_food("2 idli"))["note"]


def test_food_reply_and_place_order_buttons(monkeypatch):
    monkeypatch.setattr(main, "save_verdict", lambda *a, **k: None)
    monkeypatch.setattr(main, "get_session_manager", lambda *_a: None)

    class Agent:
        messages = []

        def __call__(self, prompt):
            req = current()
            req.actions.append("errand_food")
            req.direct_reply = "Sri Krishna Tiffins on Swiggy: 2 idli + coffee, ₹238. Tap Place order."
            req.food_pending = {"token": "t1", "total": 238.0, "summary": "Sri Krishna Tiffins: 2 idli, 1 coffee"}
            return "I've asked the food helper."

    monkeypatch.setattr(main, "make_agent", lambda *_a: Agent())
    out = main.invoke({"prompt": "User's message:\nOrder 2 idli and a coffee", "user": dict(USER)})
    assert out["reply"].startswith("Sri Krishna Tiffins on Swiggy")
    assert [b["id"] for b in out["buttons"]] == ["FOOD|yes|t1", "FOOD|no|t1"] and "₹238" in out["buttons_text"]


def test_food_confirm_mode_places_the_order(monkeypatch):
    monkeypatch.setattr(food.ksw, "take_pending", lambda phone, token: {"address_id": "addr-1", "total": 238.0,
                                                                         "summary": "2 idli, 1 coffee"})
    monkeypatch.setattr(food.ksw, "access_token", lambda phone: "tok")
    monkeypatch.setattr(food, "client_for", lambda token: FakeClient(238))
    out = main.invoke({"mode": "food_confirm", "token": "t1", "user": dict(USER, language="te")})
    assert out["reply"].startswith("✅ Swiggyలో ఆర్డర్ అయింది") and "₹238" in out["reply"]


def test_food_confirm_twice_orders_once(monkeypatch, dedupe):
    pending = ksw.create_pending(PHONE, "addr-1", 238.0, "2 idli")
    monkeypatch.setattr(food.ksw, "access_token", lambda phone: "tok")
    client = FakeClient(238)
    monkeypatch.setattr(food, "client_for", lambda token: client)
    first = main.invoke({"mode": "food_confirm", "token": pending["token"], "user": dict(USER)})
    second = main.invoke({"mode": "food_confirm", "token": pending["token"], "user": dict(USER)})
    assert first["reply"].startswith("✅") and second["reply"].startswith("Nothing was ordered")
    assert [c[0] for c in client.calls].count("place_food_order") == 1


# ----------------------------------------------------------------------------- Lambdas

def test_inbound_lambda_food_taps_and_link_command(monkeypatch):
    import app

    sent, agent_calls, dropped = [], [], []
    monkeypatch.setattr(app.kc, "wa_text", lambda to, body: sent.append(body))
    monkeypatch.setattr(app, "call_agent", lambda user, prompt, media, mid, mode=None, extra=None:
                        agent_calls.append((mode, extra)) or {"reply": "✅ ordered"})
    monkeypatch.setattr(app.ksw, "take_pending", lambda phone, token: dropped.append(token))
    app.handle_choice(PHONE, dict(USER), None, "FOOD|yes|t1")
    app.handle_choice(PHONE, dict(USER), None, "FOOD|no|t2")
    assert agent_calls == [("food_confirm", {"token": "t1"})] and dropped == ["t2"]
    assert sent[1] == "✅ ordered" and sent[2].startswith("Cancelled")
    assert app.handle_command(PHONE, dict(USER), "LINK SWIGGY")
    assert "waiting for Swiggy's approval" in sent[-1]
    monkeypatch.setattr(app.ksw, "enabled", lambda: True)
    monkeypatch.setattr(app.ksw, "start_link", lambda phone: "https://mcp.swiggy.com/auth/authorize?x=1")
    app.handle_command(PHONE, dict(USER), "link swiggy")
    assert "https://mcp.swiggy.com/auth/authorize?x=1" in sent[-1]


def _link_app():
    path = Path(__file__).resolve().parent.parent / "functions" / "swiggy_link" / "app.py"
    spec = importlib.util.spec_from_file_location("swiggy_link_app", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_swiggy_callback(monkeypatch):
    link = _link_app()
    sent = []
    monkeypatch.setattr(link.ksw, "finish_link", lambda code, state: PHONE if code == "good" else (_ for _ in ()).throw(
        ksw.NotLinked("This sign-in link has expired.")))
    monkeypatch.setattr(link.kc, "wa_text", lambda to, body: sent.append((to, body)))
    ok = link.handler({"rawPath": "/callback", "queryStringParameters": {"code": "good", "state": "s"}}, None)
    assert ok["statusCode"] == 200 and sent[0][0] == PHONE and "linked" in sent[0][1]
    assert link.handler({"rawPath": "/callback", "queryStringParameters": {"code": "bad", "state": "s"}}, None)["statusCode"] == 400
    assert link.handler({"rawPath": "/callback", "queryStringParameters": {}}, None)["statusCode"] == 400
    assert link.handler({"rawPath": "/other"}, None)["statusCode"] == 404
