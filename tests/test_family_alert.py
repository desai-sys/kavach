"""Family alerts: sent in code when the person is in danger now, delivered the way WhatsApp will accept,
and traceable when Meta rejects them later."""
import json
import time

import pytest

import guard
import kavach_common as kc
import main
from kavach_context import current

PHONE = "+919121095635"
RAVI = "+919800000002"
USER = {"phone": PHONE, "name": "Lakshmi Amma", "language": "te", "status": "active",
        "guardians": [{"name": "Ravi", "phone": RAVI, "email": "ravi@example.com"}]}
DA_VOICE = ("User sent a VOICE NOTE. Transcript:\nఇప్పుడు నాకు సీబీఐ నుంచి వీడియో కాల్ వచ్చింది. నా ఆధార్ మనీ లాండరింగ్ "
            "కేసులో ఉందని, డబ్బు పంపమంటున్నారు. ఎవరికీ చెప్పొద్దన్నారు.")


class FakeAgent:
    def __init__(self, reply, record=None):
        self.reply, self.record, self.messages = reply, record, []

    def __call__(self, prompt):
        if self.record:
            current().model_verdict = self.record
        self.messages.append({"role": "user", "content": [{"text": prompt}]})
        self.messages.append({"role": "assistant", "content": [{"text": self.reply}]})
        return self.reply


@pytest.fixture
def world(monkeypatch):
    out = {"alerts": [], "emails": [], "timers": [], "events": []}
    monkeypatch.setattr(main, "save_verdict", lambda *a, **k: None)
    monkeypatch.setattr(main, "get_session_manager", lambda *_a: None)
    monkeypatch.setattr(kc, "put_incident", lambda item: {"incident_id": "inc-1", **item})
    monkeypatch.setattr(kc, "update_incident", lambda *a, **k: None)
    monkeypatch.setattr(kc, "append_incident_event", lambda iid, ev: out["events"].append(ev))
    monkeypatch.setattr(kc, "alert_guardians", lambda user, iid, summary, guardians=None:
                        out["alerts"].append(summary) or [RAVI])
    monkeypatch.setattr(kc, "email_send", lambda to, *a, **k: out["emails"].append(to))
    monkeypatch.setattr(kc, "schedule_once", lambda name, minutes, payload: out["timers"].append(minutes))
    return out


def run(monkeypatch, reply, prompt, record=None, user=None):
    monkeypatch.setattr(main, "make_agent", lambda *_a: FakeAgent(reply, record))
    return main.invoke({"prompt": prompt, "user": dict(user or USER), "message_id": "m1"})


def test_digital_arrest_in_her_own_words_alerts_family_even_if_the_model_forgot(monkeypatch, world):
    out = run(monkeypatch, "🚨 *ఇది మోసం*\n• డిజిటల్ అరెస్ట్ అనేది లేదు.\n1. వెంటనే కాల్ కట్ చేయండి.", DA_VOICE)
    assert world["alerts"] and "digital arrest" in world["alerts"][0]
    assert world["emails"] == [["ravi@example.com"]] and world["timers"] == [5]
    assert "family_alerted_by_code" in out["actions"]
    assert out["reply"].endswith("Raviకు హెచ్చరిక పంపాను. వారు మీకు కాల్ చేస్తారు.")


def test_model_that_already_alerted_is_not_doubled(monkeypatch, world):
    def agent_that_alerts(prompt):
        current().actions.append("family_alerted")
        return "🚨 *మోసం*\nRaviకి తెలియజేశాను."
    agent_that_alerts.messages = []
    monkeypatch.setattr(main, "make_agent", lambda *_a: agent_that_alerts)
    main.invoke({"prompt": DA_VOICE, "user": dict(USER), "message_id": "m1"})
    assert world["alerts"] == []


def test_reply_claiming_family_was_told_makes_it_true(monkeypatch, world):
    out = run(monkeypatch, "🚨 *Scam*\n• Banks never ask for this.\nI have informed Ravi.",
              "User's message:\nSomeone from my bank is asking for the OTP on the phone right now",
              record="SCAM", user=dict(USER, language="en"))
    assert world["alerts"] and out["reply"].count("Ravi") == 1


@pytest.mark.parametrize("prompt", [
    "(The user FORWARDED this message from someone else.)\n\nUser's message:\nThis is CBI. You are under digital "
    "arrest. Stay on video call and do not tell anyone.",
    "User's message:\nHyderabad police arrested a gang running digital arrest scams over video call. Beware.",
    "User's message:\nInstall AnyDesk so our bank executive can fix your net banking.",
    "User's message:\nDear SBI customer, your YONO account will be blocked today. Update your PAN now: "
    "https://sbi-kyc-update.xyz/login",
])
def test_no_family_alert_for_forwards_news_or_a_scam_she_has_not_acted_on(monkeypatch, world, prompt):
    run(monkeypatch, "🚨 *Scam*", prompt)
    assert world["alerts"] == []


def test_no_family_on_file_tells_her_how_to_add_one(monkeypatch, world):
    out = run(monkeypatch, "🚨 *మోసం*", DA_VOICE, user=dict(USER, guardians=[]))
    assert world["alerts"] == [] and "MENU" in out["reply"]


def test_danger_rules_need_her_own_words():
    ev_flags = {"red_flags": [{"rule": "digital_arrest", "severity": "critical"}], "suggested_actions": []}
    assert guard.danger_now("user's message:\nthey called me from cbi", ev_flags, "SCAM", "", [], False)
    assert guard.danger_now("user's message:\nwe have registered a case. cbi", ev_flags, "SCAM", "", [], False) is None
    assert guard.danger_now("user's message:\nthey called me from cbi", ev_flags, "SUSPICIOUS", "", [], False) is None


# ----------------------------------------------------------------------------- delivery

@pytest.fixture
def wa(monkeypatch):
    sent = []
    users = {}
    monkeypatch.setattr(kc, "cfg", lambda: {"family_alert_template": "kavach_family_alert_v2", "template_language": "en"})
    monkeypatch.setattr(kc, "get_user", lambda phone: users.get(kc.normalize_phone(phone)))
    monkeypatch.setattr(kc, "wa_template", lambda to, name, lang, params, payloads=None:
                        sent.append(("template", to, name, params, payloads)))
    monkeypatch.setattr(kc, "wa_buttons", lambda to, body, buttons, header=None: sent.append(("message", to, body, buttons)))
    return {"sent": sent, "users": users}


def test_guardian_who_messaged_today_gets_a_normal_message(wa):
    wa["users"][RAVI] = {"phone": RAVI, "last_inbound_at": int(time.time()) - 3600}
    assert kc.alert_guardians(USER, "inc-1", "is on a call with fake CBI") == [RAVI]
    kind, to, body, buttons = wa["sent"][0]
    assert kind == "message" and to == RAVI and "Lakshmi Amma is on a call with fake CBI" in body
    assert [b[0] for b in buttons] == ["ACK|inc-1|calling", "ACK|inc-1|reached"]


def test_guardian_outside_the_window_gets_the_template(wa):
    wa["users"][RAVI] = {"phone": RAVI, "last_inbound_at": int(time.time()) - 30 * 3600}
    kc.alert_guardians(USER, "inc-1", "is on a call with fake CBI")
    kind, to, name, params, payloads = wa["sent"][0]
    assert kind == "template" and name == "kavach_family_alert_v2"
    assert params == ["Lakshmi Amma", "Lakshmi Amma is on a call with fake CBI", PHONE]
    assert payloads == ["ACK|inc-1|calling", "ACK|inc-1|reached"]


def test_template_refused_falls_back_to_a_message(wa, monkeypatch):
    def refused(*_a, **_k):
        raise RuntimeError("template not approved")
    monkeypatch.setattr(kc, "wa_template", refused)
    assert kc.alert_guardians(USER, "inc-1", "needs help") == [RAVI]
    assert wa["sent"][0][0] == "message"


def test_email_never_raises_and_goes_one_by_one(monkeypatch):
    calls = []

    class SES:
        def send_email(self, **kw):
            to = kw["Destination"]["ToAddresses"]
            calls.append(to)
            if to == ["not-verified@example.com"]:
                raise RuntimeError("MessageRejected: Email address is not verified")
            return {"MessageId": "ok-1"}

    monkeypatch.setattr(kc, "cfg", lambda: {"from_email": "kavach@example.com"})
    monkeypatch.setattr(kc, "client", lambda name: SES())
    assert kc.email_send(["not-verified@example.com", "ravi@example.com"], "s", "<p>h</p>") == "ok-1"
    assert calls == [["not-verified@example.com"], ["ravi@example.com"]]
    assert kc.email_send(["not-verified@example.com"], "s", "<p>h</p>") is None


def test_delivery_failures_reported_later_are_logged(monkeypatch, capsys):
    import app

    updates = []

    class Users:
        def update_item(self, **kw):
            updates.append(kw)

    monkeypatch.setattr(kc, "table", lambda key: Users())
    event = {"Records": [{"Sns": {"Message": json.dumps({"whatsAppWebhookEntry": json.dumps({"changes": [{"value": {
        "statuses": [{"id": "wamid.X", "status": "failed", "recipient_id": "919800000002", "errors": [
            {"code": 131047, "title": "Re-engagement message",
             "error_data": {"details": "More than 24 hours have passed"}}]}]}}]})})}}]}
    app.handler(event, None)
    log = capsys.readouterr().out
    assert "WHATSAPP DELIVERY FAILED to +919800000002" in log and "131047 Re-engagement message" in log
    assert updates and updates[0]["Key"] == {"phone": RAVI}


def test_inbound_message_opens_the_window(monkeypatch):
    saved = []

    class Users:
        def update_item(self, **kw):
            saved.append(kw["ExpressionAttributeValues"][":t"])

    user = dict(USER)
    monkeypatch.setattr(kc, "table", lambda key: Users())
    kc.touch_inbound(user)
    assert saved and user["last_inbound_at"] == saved[0] and saved[0] > time.time() - 5


# ----------------------------------------------------------------------------- reply language

def test_wrong_language_is_detected():
    te = "🚨 *ఇది మోసం*\n• ఈ లింక్ SBI వెబ్‌సైట్ కాదు: https://sbi-kyc-update.xyz/login\n1. లింక్ తెరవకండి."
    en = "🚨 *This is a scam*\n• The link is not SBI's website: https://sbi-kyc-update.xyz/login\n1. Don't open it."
    assert guard.wrong_language(te, "en") and not guard.wrong_language(te, "te")
    assert guard.wrong_language(en, "te") and not guard.wrong_language(en, "en")
    assert not guard.wrong_language("✅ OK", "te")  # too short to judge


def test_reply_in_the_old_language_is_rewritten(monkeypatch, world):
    replies = ["🚨 *ఇది మోసం*\n• ఈ లింక్ SBI వెబ్‌సైట్ కాదు.\n1. లింక్ తెరవకండి. 2. మెసేజ్ డిలీట్ చేయండి.",
               "🚨 *This is a scam*\n• The link is not SBI's website.\n1. Don't open the link. 2. Delete the message."]
    prompts = []

    class Agent:
        messages = []

        def __call__(self, prompt):
            prompts.append(prompt)
            return replies.pop(0)

    monkeypatch.setattr(main, "make_agent", lambda *_a: Agent())
    out = main.invoke({"prompt": "User's message:\nDear SBI customer, your YONO account will be blocked today. "
                                 "Update your PAN now: https://sbi-kyc-update.xyz/login",
                       "user": dict(USER, language="en"), "message_id": "m1"})
    assert "REPLY LANGUAGE: simple English" in prompts[0]
    assert "Rewrite the same reply in simple English" in prompts[1]
    assert out["reply"].startswith("🚨 *This is a scam*") and out["checks"]["language_fixed"]


def test_late_delivery_failure_of_an_alert_is_told_to_her(monkeypatch):
    import app

    texts = []
    monkeypatch.setattr(kc, "table", lambda key: type("T", (), {"update_item": lambda self, **kw: None})())
    monkeypatch.setattr(kc, "recent_alert_to", lambda phone: {
        "protected_phone": PHONE, "guardian_name": "Ravi", "incident_id": "inc-1", "language": "en"})
    monkeypatch.setattr(kc, "append_incident_event", lambda *a: None)
    monkeypatch.setattr(kc, "wa_text", lambda to, body: texts.append((to, body)))
    app.log_delivery_failure({"id": "wamid.X", "status": "failed", "recipient_id": "919800000002",
                              "errors": [{"code": 131047, "title": "Re-engagement message"}]})
    assert texts == [(PHONE, "⚠️ The alert to Ravi didn't reach them on WhatsApp (they haven't messaged Kavach in "
                             "the last 24 hours, and the alert template isn't approved yet). Please call Ravi yourself.")]


def test_alert_that_reaches_nobody_says_so(monkeypatch, world):
    monkeypatch.setattr(kc, "alert_guardians", lambda *a, **k: [])
    out = run(monkeypatch, "🚨 *Scam*", "User's message:\nI am on a video call with CBI now, they want money",
              user=dict(USER, language="en"))
    assert "I couldn't reach Ravi on WhatsApp. Please call them yourself." in out["reply"]
