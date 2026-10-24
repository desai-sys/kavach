"""SOS: HELP / SOS / బచావో / बचाओ alerts the family in seconds, then their location follows."""
import json
import re
import time

import pytest

import kavach_common as kc
import kavach_sos as ksos

PHONE = "+919121095635"
RAVI = "+919800000002"
SHIKHA = "+919811111111"
LOC = {"latitude": 15.828126, "longitude": 78.037279, "name": "Kurnool bus stand", "address": "Kurnool"}
LINK = "https://maps.google.com/?q=15.828126,78.037279"


def amma(**kw):
    return {"phone": PHONE, "name": "Lakshmi Amma", "language": "en", "status": "active",
            "guardians": [{"name": "Ravi", "phone": RAVI, "email": "ravi@example.com"},
                          {"name": "Shikha", "phone": SHIKHA}], **kw}


class World:
    def __init__(self):
        self.users, self.incidents, self.out, self.emails, self.timers, self.agent = {}, {}, [], [], [], []

    def kinds(self, to):
        return [m for m in self.out if m[1] == to]


class UsersTable:
    def __init__(self, w):
        self.w = w

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames=None, ExpressionAttributeValues=None,
                    ConditionExpression=None):
        user = self.w.users.setdefault(Key["phone"], {"phone": Key["phone"]})
        for name, value in re.findall(r"(#?\w+) = (:\w+)", UpdateExpression):
            field = (ExpressionAttributeNames or {}).get(name, name)
            user[field] = kc.to_jsonable(ExpressionAttributeValues[value])


class Dedupe:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None):
        self.items[Item["message_id"]] = Item

    def get_item(self, Key):
        return {"Item": self.items[Key["message_id"]]} if Key["message_id"] in self.items else {}

    def delete_item(self, Key):
        self.items.pop(Key["message_id"], None)


@pytest.fixture
def w(monkeypatch):
    import app

    world = World()
    tables = {"users_table": UsersTable(world), "dedupe_table": Dedupe()}
    monkeypatch.setattr(kc, "cfg", lambda: {"family_alert_template": "kavach_family_alert_v2", "template_language": "en",
                                            "region": "ap-south-1"})
    monkeypatch.setattr(kc, "table", lambda key: tables[key])
    monkeypatch.setattr(kc, "get_user", lambda p: json.loads(json.dumps(world.users[kc.normalize_phone(p)]))
                        if kc.normalize_phone(p) in world.users else None)
    monkeypatch.setattr(kc, "put_user", lambda u: world.users.__setitem__(kc.normalize_phone(u["phone"]),
                                                                       json.loads(json.dumps(u))))
    monkeypatch.setattr(kc, "wa_mark_read", lambda *_a: None)
    monkeypatch.setattr(kc, "wa_text", lambda to, body: world.out.append(("text", kc.normalize_phone(to), body)))
    monkeypatch.setattr(kc, "wa_buttons", lambda to, body, buttons, header=None:
                        world.out.append(("buttons", kc.normalize_phone(to), body, buttons)))
    monkeypatch.setattr(kc, "wa_template", lambda to, name, lang, params, payloads=None:
                        world.out.append(("template", kc.normalize_phone(to), params, payloads)))
    monkeypatch.setattr(kc, "wa_send", lambda msg: world.out.append((msg["type"], kc.normalize_phone(msg["to"]), msg)))
    monkeypatch.setattr(kc, "email_send", lambda to, subject, html, text=None, reply_to=None:
                        world.emails.append((to, subject, text)))

    def put_incident(item):
        item = {"incident_id": f"inc-{len(world.incidents) + 1}", **item}
        world.incidents[item["incident_id"]] = item
        return item

    monkeypatch.setattr(kc, "put_incident", put_incident)
    monkeypatch.setattr(kc, "update_incident", lambda iid, **f: world.incidents[iid].update(f))
    monkeypatch.setattr(kc, "append_incident_event", lambda iid, ev: world.incidents[iid].setdefault("events", []).append(ev))
    monkeypatch.setattr(kc, "schedule_once", lambda name, minutes, payload: world.timers.append((minutes, payload)))
    monkeypatch.setattr(app, "_first_time_seen", lambda _mid: True)
    monkeypatch.setattr(app, "call_agent", lambda *a, **k: world.agent.append(a) or {"reply": "checked"})
    # Ravi messaged Kavach an hour ago (normal messages reach him); Shikha never did (template only).
    world.users[RAVI] = {"phone": RAVI, "name": "Ravi", "status": "active", "last_inbound_at": int(time.time()) - 3600}
    counter = {"n": 0}

    def send(body=None, *, frm=PHONE, choice=None, location=None, mtype=None, forwarded=False):
        counter["n"] += 1
        msg = {"id": f"wamid.{counter['n']}", "from": frm.lstrip("+")}
        if choice:
            msg.update(type="interactive", interactive={"type": "button_reply", "button_reply": {"id": choice}})
        elif location:
            msg.update(type="location", location=location)
        elif mtype:
            msg.update(type=mtype, errors=[{"code": 131051, "title": "Message type unknown"}])
        else:
            msg.update(type="text", text={"body": body})
            if forwarded:
                msg["context"] = {"forwarded": True}
        world.out.clear()
        app.process_message(msg, "Amma")

    world.send = send
    return world


@pytest.mark.parametrize("text", ["HELP", "help!", "Please help me now", "SOS", "sos!!!", "panic", "Emergency",
                                  "బచావో", "నాకు సహాయం కావాలి", "కాపాడండి", "मदद करो", "बचाओ", "मुझे मदद चाहिए"])
def test_sos_words(text):
    assert ksos.is_sos(text)


@pytest.mark.parametrize("text", ["help me check this link", "Is this a scam? help", "I need help with my KYC",
                                  "thank you", ""])
def test_not_sos(text):
    assert not ksos.is_sos(text)
    assert not ksos.is_sos("HELP", forwarded=True)


def test_help_alerts_family_then_location_follows_then_safe(w):
    w.users[PHONE] = amma()
    w.send("HELP")
    # family: Ravi (messaged today) gets a normal message, Shikha the approved template
    ravi = w.kinds(RAVI)
    assert ravi[0][0] == "buttons" and "Lakshmi Amma pressed SOS on Kavach and needs help now" in ravi[0][2]
    assert [b[0] for b in ravi[0][3]] == ["ACK|inc-1|calling", "ACK|inc-1|reached"]
    shikha = w.kinds(SHIKHA)
    assert shikha[0][0] == "template" and shikha[0][2][1] == "Lakshmi Amma pressed SOS on Kavach and needs help now"
    assert w.emails and w.emails[0][0] == ["ravi@example.com"] and w.timers == [(5, {
        "kind": "family_escalation", "incident_id": "inc-1", "step": 1})]
    # Amma: who was told, 112, I'm safe now, and WhatsApp's Send location button
    mine = w.kinds(PHONE)
    assert mine[0][0] == "buttons" and mine[0][2].startswith("🆘 I've alerted Ravi, Shikha.") and "112" in mine[0][2]
    assert mine[0][3] == [("SOS|safe|inc-1", "I'm safe now")]
    assert mine[1][0] == "interactive" and mine[1][2]["interactive"]["type"] == "location_request_message"
    assert w.incidents["inc-1"]["type"] == "sos" and w.users[PHONE]["sos"]["incident_id"] == "inc-1"
    assert not w.agent

    w.send(location=LOC)
    pin = [m for m in w.kinds(RAVI) if m[0] == "location"][0][2]["location"]
    assert (pin["latitude"], pin["longitude"]) == (LOC["latitude"], LOC["longitude"])
    assert any(LINK in m[2] for m in w.kinds(RAVI) if m[0] == "buttons")
    assert not [m for m in w.kinds(SHIKHA) if m[0] == "location"]  # outside the window: no pin...
    assert any(LINK in m[2][1] for m in w.kinds(SHIKHA) if m[0] == "template")  # ...but the link in the template
    assert any(LINK in (e[2] or "") for e in w.emails)
    assert w.kinds(PHONE)[-1] == ("text", PHONE, "📍 Sent your location to Ravi, Shikha.")
    assert LINK in w.incidents["inc-1"]["summary"]  # the 5-minute re-alert repeats it

    w.send(choice="SOS|safe|inc-1")
    assert w.incidents["inc-1"]["family_status"] == "resolved"  # escalation stops
    assert any("says they are safe now" in m[2] for m in w.kinds(RAVI) if m[0] == "buttons")
    assert w.kinds(PHONE)[-1] == ("text", PHONE, "✅ Good. I've told Ravi, Shikha that you are safe.")


def test_sos_works_in_telugu_and_while_paused(w):
    w.users[PHONE] = amma(language="te", status="stopped")
    w.send("బచావో")
    mine = w.kinds(PHONE)
    assert mine[0][2].startswith("🆘 Ravi, Shikhaకు హెచ్చరిక పంపాను.")
    assert mine[1][2]["interactive"]["body"]["text"].startswith("📍 మీరు ఎక్కడ ఉన్నారో")


def test_fresh_location_goes_with_the_first_alert(w):
    w.users[PHONE] = amma(last_location={"lat": 15.828126, "lng": 78.037279, "label": "", "at": int(time.time()) - 60})
    w.send("SOS")
    assert LINK in w.kinds(RAVI)[0][2]
    assert [m for m in w.kinds(RAVI) if m[0] == "location"]
    assert not [m for m in w.kinds(PHONE) if m[0] == "interactive"]  # no need to ask for it


def test_no_family_yet(w):
    w.users[PHONE] = amma(guardians=[])
    w.send("help")
    assert w.kinds(PHONE) == [("text", PHONE, ksos.T["no_family"]["en"])]


def test_family_not_reached_is_said_plainly(w, monkeypatch):
    def refused(*_a, **_k):
        raise RuntimeError("(ValidationException) template not approved")
    monkeypatch.setattr(kc, "wa_template", refused)
    monkeypatch.setattr(kc, "wa_buttons", lambda to, body, buttons, header=None: (_ for _ in ()).throw(
        RuntimeError("blocked")) if kc.normalize_phone(to) != PHONE else w.out.append(("buttons", PHONE, body, buttons)))
    w.users[PHONE] = amma()
    w.send("HELP")
    text = w.kinds(PHONE)[0][2]
    assert "couldn't reach Ravi, Shikha" in text and "call 112" in text


def test_location_without_sos_is_offered_to_family(w):
    w.users[PHONE] = amma()
    w.send(location=LOC)
    assert w.kinds(PHONE)[0][3] == [("SOS|share|-", "Send to family"), ("SOS|noshare|-", "No")]
    w.send(choice="SOS|share|-")
    assert [m for m in w.kinds(RAVI) if m[0] == "location"]
    assert any("shared their location with you" in m[2] for m in w.kinds(RAVI) if m[0] == "buttons")


def test_live_location_during_sos_gets_how_to_share(w):
    w.users[PHONE] = amma()
    w.send("HELP")
    w.send(mtype="unsupported")
    assert "Send your current location" in w.kinds(PHONE)[0][2] and not w.agent


def test_new_person_saying_help_hears_112_first(w):
    w.send("help", frm="+919822222222")
    texts = [m[2] for m in w.out]
    assert texts[0].startswith("🆘 If you're in danger, call 112 now.") and "Choose your language" in texts[1]


def test_forwarded_help_is_checked_not_an_sos(w):
    w.users[PHONE] = amma()
    w.send("HELP", forwarded=True)
    assert w.agent and not w.kinds(RAVI)


def test_agent_can_start_an_sos_from_her_own_words(w):
    from kavach_context import current, start_request
    from tools import act

    w.users[PHONE] = amma()
    start_request(user={k: v for k, v in amma().items() if k != "status"})
    out = json.loads(act.send_sos("says someone is following them and needs help now"))
    assert out["alerted"] == ["Ravi", "Shikha"] and "sos_started" in current().actions
    assert "Lakshmi Amma says someone is following them and needs help now" in w.kinds(RAVI)[0][2]
    assert w.users[PHONE]["sos"]["incident_id"] == out["incident_id"]
