"""Member businesses: claims checked against the business's own records, buttons, and official actions."""
import re
from datetime import date

import pytest

import evidence as ev
import kavach_business as kb
import kavach_common as kc
import main

TODAY = date(2026, 10, 23)  # a Friday
PHONE = "+919800000001"
USER = {"phone": PHONE, "name": "Lakshmi Amma", "language": "te", "district": "Kurnool", "email": "",
        "guardians": [{"name": "Ravi", "phone": "+919800000002"}], "status": "active"}


@pytest.fixture
def records(monkeypatch):
    """PHONE is a customer of every member business, with the demo records as of TODAY."""
    store = {bid: kb.demo_record(bid, PHONE, "Lakshmi Amma", today=TODAY, visit_code="4827") for bid in kb.PROFILES}
    monkeypatch.setattr(kb, "get_record", lambda bid, phone: store.get(bid) if kc.normalize_phone(phone) == PHONE else None)
    monkeypatch.setattr(kb, "_today", lambda: TODAY)
    return store


@pytest.fixture
def outbox(monkeypatch):
    """Capture WhatsApp texts, emails, incident events and signals instead of calling AWS."""
    sent = {"wa": [], "email": [], "events": [], "signals": [], "updates": []}
    monkeypatch.setattr(kc, "cfg", lambda: {"bank_fraud_email": "desk@example.com", "region": "ap-south-1"})
    monkeypatch.setattr(kc, "wa_text", lambda to, body: sent["wa"].append((to, body)))
    monkeypatch.setattr(kc, "email_send", lambda to, subject, html, text=None, reply_to=None:
                        sent["email"].append((to, subject, text)))
    monkeypatch.setattr(kc, "append_incident_event", lambda inc, event: sent["events"].append((inc, event)))
    monkeypatch.setattr(kb, "record_signal", lambda bid, kind, **kw: sent["signals"].append((bid, kind, kw)))
    monkeypatch.setattr(kb, "_update_status", lambda bid, phone, **kw: sent["updates"].append((bid, phone, kw)))
    return sent


# ----------------------------------------------------------------------------- profiles

def test_profiles_are_complete():
    for bid, p in kb.PROFILES.items():
        for key in ("name", "short_name", "kind", "aliases", "brand_tokens", "official_domains", "how_you_pay",
                    "never", "actions", "demo_record"):
            assert p.get(key), f"{bid} is missing {key}"
        kinds = [a["kind"] for a in p["actions"]]
        assert "callback" in kinds and "report" in kinds
        for a in p["actions"]:
            for lang in kb.LANGS:
                assert 0 < len(a["title"][lang]) <= 20, f"{bid}/{a['id']}/{lang} button title too long"
        record = kb.demo_record(bid, PHONE, today=TODAY)
        assert not re.search(r"\{(iso:|today|next_saturday|visit_code)", str(record)), f"{bid}: unfilled placeholder"
        assert set(record["summary"]) == set(kb.LANGS)


def test_detects_business_by_name_website_and_sender_id():
    assert kb.detect("Dear Nidhira Health customer, your policy...")[0] == {"id": "nidhira_health", "detected_by": "name"}
    assert kb.detect("నిధిరా హెల్త్ పాలసీ రద్దు")[0]["id"] == "nidhira_health"
    assert kb.detect("कल्पवि बैंक से संदेश")[0]["id"] == "kalpavi_bank"
    link = ev.extract("Update now: kalpavibank-kyc.top/update")["links"]
    assert kb.detect("Update now: kalpavibank-kyc.top/update", link)[0] == {"id": "kalpavi_bank", "detected_by": "website"}
    assert kb.detect("VM-KLPAVI-S: Rs 2,000 debited", sms_header="VM-KLPAVI-S")[0]["detected_by"] == "sms_header"
    assert kb.detect("Amma, I reached Bengaluru safely. Will call you tonight.") == []
    assert kb.find("nidhira") == "nidhira_health" and kb.find("Kalpavi Bank") == "kalpavi_bank"
    assert kb.find("SBI") is None


def test_claims_ignore_genuine_wording():
    assert kb.claims_in("If not done by you, SMS BLOCK to 9223008333") == []
    assert kb.claims_in("Your KYC has been successfully updated.") == []
    assert kb.claims_in("Your no claim bonus of 10% is added to your cover") == []
    assert kb.claims_in("Your delivery is delayed due to rain") == ["delivery_issue"]
    assert kb.claims_in("We will notify you in advance of the visit") == []


def test_indian_money_format():
    assert kb.money(500000) == "5,00,000" and kb.money(14200) == "14,200" and kb.money(412) == "412"


# ----------------------------------------------------------------------------- claims vs records

BUSINESS_SCAMS = [
    ("insurer_lapse", "Dear Nidhira Health customer, your policy NHI-2025-004471 will lapse today. Pay premium "
                      "Rs 14,200 now at https://nidhira-renew.xyz or UPI nidhira.renewal@ybl to keep your cover.",
     {"contradicts_records", "unofficial_channel", "lookalike_domain"}),
    ("bank_kyc", "Kalpavi Bank: Dear customer, your account will be blocked today as your KYC has expired. "
                 "Update KYC now: kalpavi-kyc.top/update",
     {"contradicts_records", "unofficial_channel", "lookalike_domain"}),
    ("bank_fake_debit", "Kalpavi Bank alert: Rs 49,999 debited from your account. If not done by you, call our "
                        "officer on 9876543210 immediately.",
     {"contradicts_records", "personal_number_for_institution"}),
    ("credited_by_mistake", "Hello, I sent Rs 5,000 to your Kalpavi account by mistake, it is credited. "
                            "Please return to sanjay.k@okicici", {"contradicts_records", "unofficial_channel"}),
    ("cleaning_advance", "Chamak Home Services: your deep cleaning slot on Saturday is pending. Pay Rs 999 advance "
                         "to chamak.booking@okaxis within 1 hour, else your booking will be cancelled.",
     {"against_business_policy", "contradicts_records", "unofficial_channel"}),
    ("pharmacy_hold", "Dawaghar Pharmacy: your medicine order is on hold due to pending payment of Rs 1,250. "
                      "Pay now at https://dawaghar-pay.top to avoid cancellation.",
     {"contradicts_records", "unofficial_channel", "lookalike_domain"}),
    ("insurer_telugu", "నిధిరా హెల్త్ పాలసీ ఈరోజు రద్దు అవుతుంది. వెంటనే చెల్లించండి", {"contradicts_records"}),
]


@pytest.mark.parametrize("name,text,rules", BUSINESS_SCAMS, ids=[c[0] for c in BUSINESS_SCAMS])
def test_business_scams_contradict_records(records, name, text, rules):
    e = ev.build(text, user_phone=PHONE)
    fired = {f["rule"] for f in e["red_flags"]}
    assert rules <= fired, f"{name}: expected {rules}, got {fired}"
    assert ev.VERDICT_ORDER.index(e["verdict_floor"]) >= ev.VERDICT_ORDER.index("LIKELY_SCAM")
    assert e["business_check"]["is_customer"]
    assert [f["id"] for f in e["red_flags"]] == [f"F{i}" for i in range(1, len(e["red_flags"]) + 1)]


def test_leaked_amount_is_not_trusted(records):
    e = ev.build(BUSINESS_SCAMS[0][1], user_phone=PHONE)
    findings = " ".join(f["finding"] for f in e["red_flags"])
    assert "not due until 15 Mar 2027" in findings
    assert "active until 31 Mar 2027" in findings


BUSINESS_GENUINE = [
    ("bank_debit_sms", "VM-KLPAVI-S: Rs 2,000.00 debited from A/c XX4821 on 22-10-26 via UPI to Sri Lakshmi Kirana. "
                       "Not you? Call the number on the back of your card. - Kalpavi Bank", "Matches Kalpavi Bank's records"),
    ("pharmacy_reminder", "Dawaghar: your Metformin 500 mg refill (Rs 412) is due on 28 Oct. Pay on delivery.",
     "next payment of ₹412"),
    ("insurer_reminder", "Nidhira Health Insurance: premium of Rs 14,200 for policy NHI-2025-004471 is due on "
                         "15 Mar 2027. Renew in the Nidhira app or at https://nidhirahealth.in", "official Nidhira"),
    ("cleaning_reminder", "Chamak Home Services: your Deep cleaning (2BHK) is on Saturday at 10:00 AM. Suresh K. will "
                          "share your visit code at the door. Pay in the app after the job.", None),
]


@pytest.mark.parametrize("name,text,signal", BUSINESS_GENUINE, ids=[c[0] for c in BUSINESS_GENUINE])
def test_genuine_business_messages_have_no_floor(records, name, text, signal):
    e = ev.build(text, user_phone=PHONE)
    assert e["verdict_floor"] is None, f"{name}: unexpected flags {e['red_flags']}"
    assert e["business_check"]
    if signal:
        assert any(signal in g for g in e["genuine_signals"]), e["genuine_signals"]


def test_not_a_customer_still_gets_published_rules(records):
    text = "Chamak Home Services: pay Rs 499 booking fee to confirm your slot at chamak.slots@ybl"
    e = ev.build(text, user_phone="+919811111111")
    check = e["business_check"]
    assert not check["is_customer"] and "No Chamak Home Services record" in check["note"]
    assert {"against_business_policy", "unofficial_channel"} <= {f["rule"] for f in e["red_flags"]}


def test_records_unreachable(monkeypatch):
    def down(*_a):
        raise RuntimeError("DynamoDB down")

    monkeypatch.setattr(kb, "get_record", down)
    check = ev.build("Your Nidhira policy will lapse today, pay now", user_phone=PHONE)["business_check"]
    assert "could not be reached" in check["note"]


def test_member_websites_are_grounded():
    assert ev.ungrounded_contacts("The real website is nidhirahealth.in", "") == []
    assert ev.ungrounded_contacts("Visit nidhira-renew.xyz", "") == ["nidhira-renew.xyz"]


def test_official_websites_are_never_reported():
    e = {"identifiers": ["nidhirahealth.in", "nidhira-renew.xyz", "nidhira.renewal@ybl"]}
    assert ev.identifiers_for_report(e) == ["nidhira-renew.xyz", "nidhira.renewal@ybl"]


# ----------------------------------------------------------------------------- buttons and actions

def test_buttons_offer_report_only_for_risky_verdicts():
    risky = kb.buttons_for("nidhira_health", "LIKELY_SCAM", "te", "inc-1")
    assert [b["title"] for b in risky] == ["నా అసలు పాలసీ", "నాకు కాల్ చేయండి", "మోసం రిపోర్ట్"]
    assert risky[0]["id"] == "BIZ|nidhira_health|policy|inc-1"
    safe = kb.buttons_for("dawaghar", "LIKELY_SAFE", "en")
    assert [b["title"] for b in safe] == ["Reserve my refill", "My medicines", "Call me back"]
    assert all(b["id"].endswith("|-") for b in safe)
    assert kb.buttons_for("unknown", "SCAM", "en") == []
    stranger = kb.buttons_for("kalpavi_bank", "SCAM", "en", is_customer=False)
    assert [b["title"] for b in stranger] == ["Call me back", "Report this scam"]


def test_summary_action_sends_real_record_in_users_language(records, outbox):
    result = kb.perform_action(USER, "nidhira_health", "policy")
    assert result["done"] and result["action"] == "summary"
    to, body = outbox["wa"][0]
    assert to == PHONE and "31 Mar 2027 వరకు యాక్టివ్‌గా ఉంది" in body and body.startswith("📄")
    assert outbox["signals"][0][:2] == ("nidhira_health", "action")


def test_summary_is_emailed_when_user_has_email(records, outbox):
    kb.perform_action(dict(USER, language="en", email="amma@example.com"), "kalpavi_bank", "summary")
    assert outbox["email"][0][0] == ["amma@example.com"]
    assert "A copy has been emailed to you." in outbox["wa"][0][1]


def test_booking_action_shows_visit_code(records, outbox):
    kb.perform_action(dict(USER, language="en"), "chamak_home", "booking")
    body = outbox["wa"][0][1]
    assert "*4827*" in body and "Suresh K." in body


def test_refill_action_reserves(records, outbox):
    kb.perform_action(dict(USER, language="en"), "dawaghar", "refill")
    assert outbox["updates"][0][2]["refill_reserved"] is True
    assert "₹412" in outbox["wa"][0][1] and "28 Oct 2026" in outbox["wa"][0][1]


def test_callback_emails_the_business_desk(records, outbox, monkeypatch):
    monkeypatch.setattr(kc, "get_incident", lambda i: {"incident_id": i, "phone": PHONE, "check_summary": "fake KYC"})
    kb.perform_action(dict(USER, language="en"), "kalpavi_bank", "callback", "inc-9")
    assert outbox["email"][0][0] == ["desk@example.com"]
    assert "inc-9" in outbox["email"][0][2]
    assert "starting with 1600" in outbox["wa"][0][1]
    assert outbox["events"] == [("inc-9", "Kalpavi Bank: customer used 'callback'")]


def test_report_ignores_someone_elses_incident(records, outbox, monkeypatch):
    monkeypatch.setattr(kc, "get_incident", lambda i: {"incident_id": i, "phone": "+919899999999",
                                                       "scam_identifiers": ["secret.example"]})
    kb.perform_action(dict(USER, language="en"), "kalpavi_bank", "report", "inc-other")
    assert "secret.example" not in outbox["email"][0][2]
    assert outbox["events"] == []


def test_unknown_action_is_refused(records, outbox):
    result = kb.perform_action(USER, "kalpavi_bank", "transfer_money")
    assert not result["done"] and outbox["email"] == []


def test_not_a_customer_gets_no_record_message(records, outbox):
    kb.perform_action(dict(USER, phone="+919811111111", language="en"), "nidhira_health", "summary")
    assert "couldn't find a Nidhira Health Insurance record" in outbox["wa"][0][1]


# ----------------------------------------------------------------------------- agent and Lambda wiring

class FakeAgent:
    def __init__(self, reply):
        self.reply, self.messages, self.calls = reply, [], []

    def __call__(self, prompt):
        self.calls.append(prompt)
        self.messages.append({"role": "user", "content": [{"text": prompt}]})
        self.messages.append({"role": "assistant", "content": [{"text": self.reply}]})
        return self.reply


def test_agent_sees_records_and_returns_buttons(records, monkeypatch):
    monkeypatch.setattr(main, "save_verdict", lambda *a, **k: None)
    monkeypatch.setattr(main, "get_session_manager", lambda *_a: None)
    reply = ("🚨 *మోసం*\n• Nidhira మీ పాలసీ 31 Mar 2027 వరకు యాక్టివ్ అని నిర్ధారించింది.\n"
             "1. లింక్ తెరవకండి. 'నా అసలు పాలసీ' నొక్కండి.")
    agent = FakeAgent(reply)
    monkeypatch.setattr(main, "make_agent", lambda *_a: agent)
    out = main.invoke({"prompt": "User's message:\n" + BUSINESS_SCAMS[0][1], "user": dict(USER), "message_id": "m1"})
    sheet = agent.calls[0]
    assert '"business_check"' in sheet and "active until 31 Mar 2027" in sheet and "buttons_after_reply" not in sheet
    assert out["business"] == "Nidhira Health Insurance"
    assert [b["title"] for b in out["buttons"]][-1] == "మోసం రిపోర్ట్"
    assert out["verdict"] == "LIKELY_SCAM" and not out["checks"]["retried"]


def test_inbound_lambda_routes_business_taps(monkeypatch):
    import app

    calls = []
    monkeypatch.setattr(app.kb, "perform_action", lambda *a: calls.append(a))
    app.handle_choice(PHONE, dict(USER), None, "BIZ|kalpavi_bank|status|inc-1")
    app.handle_choice(PHONE, dict(USER), None, "BIZ|dawaghar|refill|-")
    app.handle_choice(PHONE, dict(USER, status="stopped"), None, "BIZ|dawaghar|refill|-")
    assert calls == [(dict(USER), "kalpavi_bank", "status", "inc-1"), (dict(USER), "dawaghar", "refill", "-")]


def test_inbound_lambda_sends_buttons_after_reply(monkeypatch):
    import app

    sent = []
    monkeypatch.setattr(app.kc, "wa_buttons", lambda to, body, buttons: sent.append((to, body, buttons)))
    app.send_buttons(PHONE, {"buttons": [{"id": "BIZ|x|y|-", "title": "Call me back"}], "buttons_text": "Hi"})
    app.send_buttons(PHONE, {"reply": "no business"})
    assert sent == [(PHONE, "Hi", [("BIZ|x|y|-", "Call me back")])]


def test_family_alert_falls_back_when_template_is_not_approved(monkeypatch):
    monkeypatch.setattr(kc, "cfg", lambda: {"family_alert_template": "kavach_family_alert", "template_language": "en"})

    def rejected(*_a, **_k):
        raise RuntimeError("template not approved")

    sent = []
    monkeypatch.setattr(kc, "wa_template", rejected)
    monkeypatch.setattr(kc, "wa_buttons", lambda to, body, buttons, header=None: sent.append((to, body, buttons)))
    out = kc.alert_guardians(USER, "inc-7", "is on a video call with someone claiming to be CBI")
    assert out == ["+919800000002"]
    to, body, buttons = sent[0]
    assert "Lakshmi Amma is on a video call" in body and buttons[0] == ("ACK|inc-7|calling", "I'm calling now")
