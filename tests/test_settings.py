"""Settings any time (language, family, pause, linked services) and no buttons that never arrive.

The inbound Lambda is driven end to end with fake WhatsApp and DynamoDB: each test sends the messages a person
would send and checks what Kavach sends back, and whether the agent was called at all.
"""
import json
import time
from datetime import datetime

import pytest

import evidence as ev
import guard
import kavach_business as kb
import kavach_clinic as kclinic
import kavach_common as kc
import kavach_settings as ks
import main
from kavach_context import current, start_request
from tools import settings as settings_tools

PHONE = "+919121095635"
RAVI = "+919800000002"
NOW = datetime(2026, 10, 23, 9, 0)  # Friday 9:00 AM IST


def active_user(**kw):
    return {"phone": PHONE, "name": "Lakshmi Amma", "language": "te", "district": "Kurnool", "status": "active",
            "consent_at": "2026-10-20T10:00:00+05:30",
            "guardians": [{"name": "Ravi", "phone": RAVI, "email": "ravi@example.com"}], **kw}


class Store:
    """Users and business records in memory, plus everything sent on WhatsApp."""

    def __init__(self):
        self.users, self.records, self.sent, self.agent_calls = {}, {}, [], []

    # kc fakes
    def get_user(self, phone):
        u = self.users.get(kc.normalize_phone(phone))
        return json.loads(json.dumps(u)) if u else None

    def put_user(self, user):
        self.users[kc.normalize_phone(user["phone"])] = json.loads(json.dumps(user))

    def texts(self):
        return [s[1] for s in self.sent if s[0] == "text"]

    def last(self, kind=None):
        return next(s for s in reversed(self.sent) if kind is None or s[0] == kind)


class RecordsTable:
    def __init__(self, store):
        self.store = store

    def get_item(self, Key):
        item = self.store.records.get((Key["business_id"], Key["phone"]))
        return {"Item": item} if item else {}

    def delete_item(self, Key):
        self.store.records.pop((Key["business_id"], Key["phone"]), None)


class UsersTable:
    def __init__(self, store):
        self.store = store

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        user = self.store.users.setdefault(Key["phone"], {"phone": Key["phone"]})
        user["pending_guardian"] = kc.to_jsonable(ExpressionAttributeValues[":g"])


@pytest.fixture
def wa(monkeypatch):
    import app

    store = Store()
    tables = {"business_records_table": RecordsTable(store), "users_table": UsersTable(store)}
    monkeypatch.setattr(kc, "table", lambda key: tables[key])
    monkeypatch.setattr(kc, "get_user", store.get_user)
    monkeypatch.setattr(kc, "put_user", store.put_user)
    monkeypatch.setattr(kc, "wa_mark_read", lambda *_a: None)
    monkeypatch.setattr(kc, "wa_text", lambda to, body: store.sent.append(("text", body, to)))
    monkeypatch.setattr(kc, "wa_buttons", lambda to, body, buttons, header=None:
                        store.sent.append(("buttons", body, [b for b in buttons], to)))
    monkeypatch.setattr(kc, "wa_list", lambda to, body, button, sections, header=None:
                        store.sent.append(("list", body, sections, button, to)))
    monkeypatch.setattr(kb, "record_signal", lambda *a, **k: None)
    monkeypatch.setattr(app, "_first_time_seen", lambda _mid: True)

    def fake_agent(user, prompt, media, message_id, mode=None):
        store.agent_calls.append(prompt)
        return {"reply": "🚨 checked"}

    monkeypatch.setattr(app, "call_agent", fake_agent)
    counter = {"n": 0}

    def send(body=None, *, choice=None, forwarded=False, contacts=None, frm=PHONE):
        counter["n"] += 1
        msg = {"id": f"wamid.{counter['n']}", "from": frm.lstrip("+")}
        if choice:
            msg.update(type="interactive", interactive={"type": "button_reply", "button_reply": {"id": choice}})
        elif contacts is not None:
            msg.update(type="contacts", contacts=contacts)
        else:
            msg.update(type="text", text={"body": body})
            if forwarded:
                msg["context"] = {"forwarded": True}
        app.process_message(msg, "Amma")

    store.send = send
    return store


# ----------------------------------------------------------------------------- recognising requests

@pytest.mark.parametrize("text,expected", [
    ("MENU", ("menu", "")), ("settings", ("menu", "")), ("మెనూ", ("menu", "")), ("सेटिंग्स", ("menu", "")),
    ("hi", ("greet", "")), ("నమస్తే", ("greet", "")), ("Hello!", ("greet", "")),
    ("change language", ("language", "")), ("భాష మార్చు", ("language", "")), ("भाषा", ("language", "")),
    ("English", ("set_language", "en")), ("తెలుగు", ("set_language", "te")), ("हिंदी", ("set_language", "hi")),
    ("Telugu lo", ("set_language", "te")),
    ("guardian", ("family", "")), ("change guardian", ("family", "")), ("కుటుంబ సభ్యులు", ("family", "")),
    ("GUARDIAN", ("family", "")), ("add family member", ("add_family", "")),
    ("GUARDIAN Ravi +919876543210 ravi@example.com", ("guardian_cmd", "Ravi +919876543210 ravi@example.com")),
    ("add my daughter Priya 98765 43210", ("add_with_number", "add my daughter Priya 98765 43210")),
    ("STOP", ("pause", "")), ("ఆపు", ("pause", "")), ("बंद करो", ("pause", "")),
    ("resume", ("resume", "")), ("చాలు", None), ("DISTRICT Kurnool", ("district", "Kurnool")),
    ("district", ("district_ask", "")), ("BANK SBI", ("bank", "SBI")), ("linked services", ("linked", "")),
    ("what can you do", ("how", "")), ("Thank you!", ("thanks", "")), ("ధన్యవాదాలు", ("thanks", "")),
])
def test_short_requests_in_three_languages(text, expected):
    assert ks.intent(text) == expected


@pytest.mark.parametrize("text", [
    "Dear customer your account will be blocked today. Update KYC now: https://sbi-kyc-update.xyz",
    "Your family member has been arrested. Call 9876543210 to stop the case",  # a scam, not "add family"
    "I have fever since yesterday",
    "Stop the payment please, I sent money to a fraud",
])
def test_messages_to_check_are_not_settings(text):
    assert ks.intent(text) is None


def test_forwarded_text_is_never_a_setting():
    assert ks.intent("STOP", forwarded=True) is None
    assert ks.intent("add guardian 9876543210", forwarded=True) is None


def test_parse_family_contact():
    assert ks.parse_contact_text("Ravi 98765 43210") == {"name": "Ravi", "phone": "+919876543210", "email": ""}
    assert ks.parse_contact_text("add my son Ravi +91 98765-43210 ravi@x.com") == {
        "name": "son Ravi", "phone": "+919876543210", "email": "ravi@x.com"}
    assert ks.parse_contact_text("Ravi 12345") is None
    card = [{"name": {"formatted_name": "Ravi Kumar"}, "phones": [{"phone": "+91 98765 43210", "wa_id": "919876543210"}],
             "emails": [{"email": "Ravi@Example.com"}]}]
    assert ks.contact_from_card(card) == {"name": "Ravi Kumar", "phone": "+919876543210", "email": "ravi@example.com"}
    assert ks.contact_from_card([{"name": {"formatted_name": "No number"}, "phones": []}]) is None


def test_every_button_and_list_label_fits_whatsapp_limits():
    """Titles WhatsApp would reject (button > 20, row > 24, description > 72) must never be sent cut short."""
    user = active_user(guardians=[{"name": "Ravi", "phone": RAVI, "email": "ravi.kumar.longname@example.com"}])
    for lang in ("en", "te", "hi"):
        for key, texts in ks.T.items():
            if key.startswith("btn_") or key.endswith("_button"):
                assert len(texts[lang]) <= 20, (key, lang, texts[lang])
        lst = ks.menu_list(dict(user, language=lang))
        family = ks.family_list(dict(user, language=lang))
        for l in (lst, family):
            assert len(l["button"]) <= 20, l["button"]
            for row in l["sections"][0]["rows"]:
                assert len(row["title"]) <= 24, row["title"]
                assert len(row["description"]) <= 72, row["description"]
        for p in kb.PROFILES.values():
            for a in p["actions"]:
                assert len(a["title"][lang]) <= 20, a["title"][lang]
    for _bid, title in ks.LANG_BUTTONS:
        assert len(title) <= 20


# ----------------------------------------------------------------------------- the WhatsApp flows

def test_new_person_onboards_and_gets_buttons_not_a_typed_command(wa):
    wa.send("hi")
    assert wa.last()[0] == "buttons" and [b[0] for b in wa.last()[2]] == ["LANG|te", "LANG|hi", "LANG|en"]
    wa.send(choice="LANG|te")
    assert [b[0] for b in wa.last()[2]] == ["CONSENT|yes", "CONSENT|no"]
    wa.send(choice="CONSENT|yes")
    kind, body, buttons, _to = wa.last()
    assert kind == "buttons" and "GUARDIAN Ravi" not in body
    assert [b[0] for b in buttons] == ["SET|add", "SET|menu"]
    assert wa.users[PHONE]["status"] == "active" and not wa.agent_calls


def test_hi_opens_the_menu_instead_of_a_scam_check(wa):
    wa.put_user(active_user())
    wa.send("Hi")
    kind, body, sections, button, _to = wa.last()
    assert kind == "list" and body.startswith("నమస్తే Lakshmi") and button == "సెట్టింగ్స్ తెరవండి"
    ids = [r["id"] for r in sections[0]["rows"]]
    assert ids == ["SET|lang", "SET|family", "SET|add", "SET|linked", "SET|district", "SET|pause", "SET|how"]
    assert sections[0]["rows"][1]["description"] == "Ravi"
    assert not wa.agent_calls


def test_change_language_midway_keeps_kavach_on(wa):
    wa.put_user(active_user())
    wa.send("change language")
    assert [b[0] for b in wa.last()[2]] == ["LANG|te", "LANG|hi", "LANG|en"]
    wa.send(choice="LANG|en")
    assert wa.last() == ("text", "✅ Language changed to English.", PHONE)
    assert wa.users[PHONE]["status"] == "active" and wa.users[PHONE]["language"] == "en"
    wa.send("हिंदी")  # typing a language name switches straight away
    assert wa.users[PHONE]["language"] == "hi" and wa.last()[1] == "✅ भाषा हिन्दी कर दी गई।"
    assert not any("CONSENT" in str(s) for s in wa.sent) and not wa.agent_calls


def test_stop_then_start_again(wa):
    wa.put_user(active_user())
    wa.send("STOP")
    assert wa.users[PHONE]["status"] == "stopped"
    assert wa.last()[0] == "buttons" and wa.last()[2] == [("SET|resume", "కవచ్ ఆన్ చేయి")]
    wa.send("Dear customer your KYC expired, update at sbi-kyc.xyz", forwarded=True)
    assert not wa.agent_calls and wa.last()[2] == [("SET|resume", "కవచ్ ఆన్ చేయి")]  # paused: not checked
    wa.send("hi")
    assert wa.users[PHONE]["status"] == "active" and wa.last()[1].startswith("▶️")
    wa.send("STOP")
    wa.send(choice="SET|resume")
    assert wa.users[PHONE]["status"] == "active"
    wa.send("Dear customer your KYC expired, update at sbi-kyc.xyz", forwarded=True)
    assert len(wa.agent_calls) == 1


def test_add_family_by_typing_then_email(wa):
    wa.put_user(active_user(guardians=[]))
    wa.send("GUARDIAN")
    assert "Contact" in wa.last()[1] and wa.users[PHONE]["awaiting"]["what"] == "guardian"
    wa.send("Priya 98765 43210")
    assert wa.users[PHONE]["guardians"] == [{"name": "Priya", "phone": "+919876543210", "email": ""}]
    assert "+91 98765 43210" in wa.last()[1]
    wa.send("priya@example.com")
    assert wa.users[PHONE]["guardians"][0]["email"] == "priya@example.com"
    assert "awaiting" not in wa.users[PHONE] and not wa.agent_calls


def test_add_family_from_a_shared_contact_card(wa):
    wa.put_user(active_user())
    card = [{"name": {"formatted_name": "Priya"}, "phones": [{"phone": "+91 91234 56789", "wa_id": "919123456789"}]}]
    wa.send(contacts=card)
    kind, body, buttons, _to = wa.last()
    assert kind == "buttons" and "Priya" in body
    assert [b[0] for b in buttons] == ["SET|addyes", "SET|checknum", "SET|addno"]
    wa.send(choice="SET|addyes")
    assert [g["name"] for g in wa.users[PHONE]["guardians"]] == ["Ravi", "Priya"]


def test_shared_contact_can_be_checked_instead(wa):
    wa.put_user(active_user())
    wa.send(contacts=[{"name": {"formatted_name": "SBI Officer"}, "phones": [{"phone": "+91 99887 76655"}]}])
    wa.send(choice="SET|checknum")
    assert len(wa.agent_calls) == 1 and "+919988776655" in wa.agent_calls[0]
    assert [g["name"] for g in wa.users[PHONE]["guardians"]] == ["Ravi"]


def test_remove_a_family_member(wa):
    wa.put_user(active_user())
    wa.send("change guardian")
    kind, _body, sections, _button, _to = wa.last()
    assert kind == "list" and [r["id"] for r in sections[0]["rows"]] == ["SET|g|919800000002", "SET|add"]
    wa.send(choice="SET|g|919800000002")
    assert [b[0] for b in wa.last()[2]] == ["SET|rm|919800000002", "SET|keep"]
    wa.send(choice="SET|rm|919800000002")
    assert wa.users[PHONE]["guardians"] == [] and "MENU" in wa.last()[1]


def test_add_with_number_asks_first_and_own_number_is_refused(wa):
    wa.put_user(active_user(language="en"))
    wa.send("add my daughter Priya 98765 43210")
    assert [b[0] for b in wa.last()[2]] == ["SET|addyes", "SET|addno"]
    assert len(wa.users[PHONE]["guardians"]) == 1  # nothing added before the tap
    wa.send(choice="SET|addno")
    assert wa.last()[1] == "OK, no change." and len(wa.users[PHONE]["guardians"]) == 1
    wa.send("GUARDIAN Me +919121095635")
    assert "your own number" in wa.last()[1]


def test_forwarded_add_request_is_checked_not_obeyed(wa):
    wa.put_user(active_user())
    wa.send("Add guardian 98765 43210 to receive your refund", forwarded=True)
    assert len(wa.agent_calls) == 1 and len(wa.users[PHONE]["guardians"]) == 1


def test_district_by_menu(wa):
    wa.put_user(active_user(language="en", district=""))
    wa.send(choice="SET|district")
    wa.send("guntur")
    assert wa.users[PHONE]["district"] == "Guntur" and "Guntur" in wa.last()[1]


def test_linked_services_show_where_records_come_from_and_unlink(wa):
    wa.put_user(active_user(language="en"))
    for bid in ("kalpavi_bank", "nidhira_health"):
        wa.records[(bid, PHONE)] = kb.demo_record(bid, PHONE, "Lakshmi Amma", today=NOW.date())
    wa.send("MENU")
    wa.send(choice="SET|linked")
    kind, body, sections, _button, _to = wa.last()
    assert kind == "list" and "registered with them" in body
    rows = sections[0]["rows"]
    assert [r["title"] for r in rows] == ["Kalpavi Bank", "Nidhira Health Insurance"]
    assert rows[0]["description"] == "Linked 2 Oct 2026 via the Kalpavi Bank app"
    wa.send(choice="SET|biz|kalpavi_bank")
    kind, body, buttons, _to = wa.last()
    assert "account status, KYC date" in body and "never sees your passwords" in body
    assert [b[0] for b in buttons] == ["SET|unlink|kalpavi_bank", "SET|keep"]
    wa.send(choice="SET|unlink|kalpavi_bank")
    assert ("kalpavi_bank", PHONE) not in wa.records and "Unlinked" in wa.last()[1]


def test_no_linked_services(wa):
    wa.put_user(active_user(language="en"))
    wa.send("linked services")
    assert wa.last()[0] == "text" and "No services are linked" in wa.last()[1]


def test_guardian_gets_the_reached_button_again(wa, monkeypatch):
    import app

    wa.put_user(active_user())
    monkeypatch.setattr(kc, "get_incident", lambda iid: {"incident_id": iid, "phone": PHONE})
    monkeypatch.setattr(kc, "update_incident", lambda *a, **k: None)
    monkeypatch.setattr(kc, "append_incident_event", lambda *a, **k: None)
    app.handle_choice(RAVI, None, "Ravi", "ACK|inc-9|calling")
    kind, _body, buttons, to = wa.last()
    assert kind == "buttons" and to == RAVI and buttons == [("ACK|inc-9|reached", "I've reached them")]


# ----------------------------------------------------------------------------- no buttons that never arrive

def test_button_talk_is_removed_from_replies():
    reply = ("✅ మీరు జ్వరంతో బాధపడుతున్నారు. *Dhanvi Family Clinic*లో అపాయింట్‌మెంట్ బుక్ చేయవచ్చు.\n\n*ఏమి చేయాలి?*\n"
             "1. క్రింద ఉన్న బటన్‌ను ట్యాప్ చేయండి, తదుపరి దశలు కనుగొనండి.\n"
             "2. మీరు డాక్టర్ సలహా కోసం ఒక సమయాన్ని ఎంచుకోవచ్చు.\n\nTap 'అపాయింట్‌మెంట్ బుక్ చేయండి' below.")
    out = guard.strip_button_talk(reply)
    assert "బటన్" not in out and "below" not in out
    assert "1. మీరు డాక్టర్ సలహా కోసం" in out and "*ఏమి చేయాలి?*" in out
    assert guard.strip_button_talk("What to do now?\n1. Tap the button below.\nDid you pay?") == "Did you pay?"
    kept = "🚨 *Scam*\n1. Don't tap any link or button in that message.\n2. It's fake; it's not from SBI."
    assert guard.strip_button_talk(kept) == kept
    assert guard.strip_button_talk("मैसेज में दिए लिंक पर टैप न करें।\nनीचे दिए गए बटन पर टैप करें।") == \
        "मैसेज में दिए लिंक पर टैप न करें।"


@pytest.mark.parametrize("text,wanted", [
    ("User's message:\nI have fever since yesterday", True),
    ("User's message:\nనిన్నటి నుంచి జ్వరం ఉంది", True),
    ("User's message:\nमेरे घुटने में दर्द है", True),
    ("User's message:\nBook a doctor for my eyes", True),
    ("(The user FORWARDED this message from someone else.)\n\nUser's message:\nDr. Rao clinic fever camp", False),
    ("User's message:\nDoctor called me and said pay Rs 500 to book the appointment", False),
    ("User's message:\nHyderabad police arrested a gang running fake hospital bills", False),
    ("User's message:\nIs this hospital link real? http://apollo-care.xyz", False),
])
def test_doctor_request_detection(text, wanted):
    e = ev.build(text, user_phone=PHONE, forwarded="FORWARDED" in text)
    assert bool(e["doctor_request"]) is wanted


class FakeAgent:
    def __init__(self, reply):
        self.reply, self.messages = reply, []

    def __call__(self, prompt):
        self.messages.append({"role": "user", "content": [{"text": prompt}]})
        self.messages.append({"role": "assistant", "content": [{"text": self.reply}]})
        return self.reply


@pytest.fixture
def clinic(monkeypatch):
    monkeypatch.setattr(kclinic, "_now", lambda: NOW)
    monkeypatch.setattr(kclinic, "_booked", lambda *_a: set())
    monkeypatch.setattr(main, "save_verdict", lambda *a, **k: None)
    monkeypatch.setattr(main, "get_session_manager", lambda *_a: None)


def test_doctor_list_is_sent_even_when_the_model_only_talks_about_a_button(clinic, monkeypatch):
    """The screenshot bug: "tap the button below" and no button. Now the times list goes out and the line goes."""
    reply = ("✅ మీరు జ్వరంతో బాధపడుతున్నారు.\n*ఏమి చేయాలి?*\n1. క్రింద ఉన్న బటన్‌ను ట్యాప్ చేయండి.\n"
             "Tap 'అపాయింట్‌మెంట్ బుక్ చేయండి' below.")
    monkeypatch.setattr(main, "make_agent", lambda *_a: FakeAgent(reply))
    out = main.invoke({"prompt": "User's message:\nI have fever since yesterday", "message_id": "m1",
                       "user": active_user()})
    rows = out["list"]["sections"][0]["rows"]
    assert rows and all("Rao" in r["description"] for r in rows)
    assert "బటన్" not in out["reply"] and "below" not in out["reply"]
    assert out["buttons"] == [] and "errand_appointment" in out["actions"]


def test_no_free_times_sends_a_real_call_me_back_button(clinic, monkeypatch):
    monkeypatch.setattr(kclinic, "free_slots", lambda *_a, **_k: [])
    monkeypatch.setattr(main, "make_agent", lambda *_a: FakeAgent("No free times this week."))
    out = main.invoke({"prompt": "User's message:\nI need a doctor for knee pain", "message_id": "m2",
                       "user": active_user(language="en")})
    assert out["list"] is None
    assert [b["title"] for b in out["buttons"]] == ["Call me back"] and out["buttons_text"]


def test_scam_about_a_doctor_gets_no_booking_list(clinic, monkeypatch):
    monkeypatch.setattr(main, "make_agent", lambda *_a: FakeAgent("🚨 *Scam*"))
    out = main.invoke({"prompt": "User's message:\nDoctor said pay Rs 500 advance by UPI to doc.desk@ybl",
                       "message_id": "m3", "user": active_user(language="en")})
    assert out["list"] is None


def test_agent_settings_tools_only_show_menus(monkeypatch):
    store = Store()
    monkeypatch.setattr(kc, "table", lambda key: {"users_table": UsersTable(store)}[key])
    start_request(user=active_user(language="en"))
    out = json.loads(settings_tools.open_settings("family"))
    assert out["shown"] and current().list_message["sections"][0]["rows"][0]["title"] == "Ravi"
    out = json.loads(settings_tools.add_family_contact("Priya", "98765 43210"))
    assert out["waiting_for_tap"] and not out["added"]
    assert [b["id"] for b in current().buttons] == ["SET|addyes", "SET|addno"]
    assert store.users[PHONE]["pending_guardian"]["phone"] == "+919876543210"
    assert store.users[PHONE]["pending_guardian"]["until"] > time.time()
    assert json.loads(settings_tools.add_family_contact("Me", PHONE))["added"] is False
    start_request(user=active_user(language="en"))
    settings_tools.open_settings("pause")
    assert [b["id"] for b in current().buttons] == ["SET|pause", "SET|keep"]
