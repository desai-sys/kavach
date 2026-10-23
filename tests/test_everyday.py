"""Everyday help: photo -> official store links, and booking a doctor at a member clinic."""
import json
from datetime import datetime

import pytest
from botocore.exceptions import ClientError

import evidence as ev
import kavach_business as kb
import kavach_clinic as kclinic
import kavach_common as kc
import main
import shopping
from kavach_context import current, start_request
from tools import everyday

PHONE = "+919121095635"
USER = {"phone": PHONE, "name": "Lakshmi Amma", "language": "en", "district": "Kurnool", "status": "active",
        "email": "amma@example.com", "guardians": [{"name": "Ravi", "phone": "+919800000002", "email": "ravi@example.com"}]}
NOW = datetime(2026, 10, 23, 9, 0)  # Friday 9:00 AM IST


# ----------------------------------------------------------------------------- shopping

AD = {"summary": "Instagram ad", "visible_text": "Prestige Svachh 5 L pressure cooker 85% OFF only Rs 499! Order on "
      "deals-kitchen.shop", "urls": ["deals-kitchen.shop"], "is_shopping_ad": True,
      "product": {"name": "Svachh pressure cooker", "brand": "Prestige", "model": "5 Litre", "price_shown_inr": 499,
                  "seller_or_site_shown": "deals-kitchen.shop"}}


def test_store_links_point_only_to_official_stores():
    links = shopping.store_links("Prestige Svachh 5 Litre")
    assert [l["store"] for l in links] == ["Amazon", "Flipkart"]
    assert links[0]["url"] == "https://www.amazon.in/s?k=Prestige+Svachh+5+Litre"
    assert ev.ungrounded_contacts(" ".join(l["url"] for l in links), "") == []
    assert shopping.product_query({"brand": "Prestige", "name": "Prestige cooker", "model": None}) == "Prestige cooker"


def test_photo_of_an_ad_gives_store_links_and_a_discount_warning(monkeypatch):
    monkeypatch.setattr(ev, "analyze_media", lambda *_a, **_k: json.dumps(AD))
    e = ev.build("Is this a good deal?", media=[{"kind": "image", "s3_uri": "s3://b/k.jpg", "mime_type": "image/jpeg"}],
                 user_phone=PHONE)
    assert e["product_lookup"]["product"] == "Prestige Svachh pressure cooker 5 Litre"
    assert e["product_lookup"]["official_store_links"][0]["url"].startswith("https://www.amazon.in/s?k=Prestige")
    assert "too_good_deal" in {f["rule"] for f in e["red_flags"]}
    assert e["verdict_floor"] == "SUSPICIOUS"


def test_big_discount_on_an_official_store_is_not_flagged():
    e = ev.build("Big Billion Days: 75% off on this mixer https://www.flipkart.com/mixer", user_phone=PHONE)
    assert "too_good_deal" not in {f["rule"] for f in e["red_flags"]}


def test_find_product_online_tool():
    start_request(user=dict(USER))
    out = json.loads(everyday.find_product_online("Bajaj 1200 mm ceiling fan"))
    assert out["official_store_links"][1]["url"] == "https://www.flipkart.com/search?q=Bajaj+1200+mm+ceiling+fan"
    assert current().actions == ["errand_shopping"]


# ----------------------------------------------------------------------------- clinic

class FakeTable:
    def __init__(self):
        self.items = {}

    def _key(self, item_or_key):
        return (item_or_key.get("business_id"), item_or_key.get("slot_id") or item_or_key.get("phone"))

    def put_item(self, Item, ConditionExpression=None):
        if ConditionExpression and self._key(Item) in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[self._key(Item)] = dict(Item)

    def get_item(self, Key):
        item = self.items.get(self._key(Key))
        return {"Item": item} if item else {}

    def delete_item(self, Key, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        item = self.items.get(self._key(Key))
        if not item or (ExpressionAttributeValues and item.get("phone") != ExpressionAttributeValues[":phone"]):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "DeleteItem")
        del self.items[self._key(Key)]


@pytest.fixture
def clinic(monkeypatch):
    bookings, records = FakeTable(), FakeTable()
    sent = {"text": [], "list": [], "buttons": [], "email": [], "timers": []}
    monkeypatch.setattr(kc, "cfg", lambda: {"region": "ap-south-1", "bank_fraud_email": "desk@example.com"})
    monkeypatch.setattr(kc, "table", lambda key: {"bookings_table": bookings, "business_records_table": records}[key])
    monkeypatch.setattr(kclinic, "_now", lambda: NOW)
    monkeypatch.setattr(kclinic, "_booked", lambda bid, start, end: {k[1] for k in bookings.items if k[0] == bid})
    monkeypatch.setattr(kc, "wa_text", lambda to, body: sent["text"].append(body))
    monkeypatch.setattr(kc, "wa_list", lambda to, body, button, sections, header=None: sent["list"].append(sections))
    monkeypatch.setattr(kc, "wa_buttons", lambda to, body, buttons, header=None: sent["buttons"].append((body, buttons)))
    monkeypatch.setattr(kc, "email_send", lambda to, subject, html, text=None, reply_to=None: sent["email"].append((to, subject)))
    monkeypatch.setattr(kc, "schedule_once", lambda name, minutes, payload: sent["timers"].append((minutes, payload)))
    monkeypatch.setattr(kc, "get_user", lambda phone: dict(USER))
    monkeypatch.setattr(kb, "record_signal", lambda *a, **k: None)
    return {"bookings": bookings, "records": records, "sent": sent}


def test_clinic_profile_has_bookable_doctors():
    p = kb.PROFILES["dhanvi_clinic"]
    assert p["kind"] == "clinic" and len(p["doctors"]) == 3
    assert kb.detect("Appointment at Dhanvi Clinic tomorrow")[0]["id"] == "dhanvi_clinic"
    assert kb.detect("Dhanvi reached school safely") == []  # a name, not the clinic


def test_right_doctor_for_the_problem():
    assert kclinic.match_doctors("dhanvi_clinic", "knee pain since a week")[0]["id"] == "dr_lakshmi"
    assert kclinic.match_doctors("dhanvi_clinic", "మోకాలు నొప్పి")[0]["id"] == "dr_lakshmi"
    assert kclinic.match_doctors("dhanvi_clinic", "eye check-up for glasses")[0]["id"] == "dr_imran"
    assert kclinic.match_doctors("dhanvi_clinic", "something else")[0]["id"] == "dr_rao"


def test_free_slots_skip_the_past_and_booked_times(clinic):
    slots = kclinic.free_slots("dhanvi_clinic", kclinic.match_doctors("dhanvi_clinic", "fever"))
    assert slots[0]["slot_id"] == "2026-10-23T10:00#dr_rao" and slots[0]["when"] == "Fri 23 Oct, 10:00 AM"
    assert len(slots) == 10 and sum(1 for s in slots if s["at"].day == 23) == 4
    clinic["bookings"].items[("dhanvi_clinic", "2026-10-23T10:00#dr_rao")] = {"phone": "+91x"}
    assert kclinic.free_slots("dhanvi_clinic", kclinic.match_doctors("dhanvi_clinic", "fever"))[0]["when"] == "Fri 23 Oct, 10:20 AM"
    lst = kclinic.slot_list("dhanvi_clinic", slots, "en")
    row = lst["sections"][0]["rows"][0]
    assert row["id"] == "SLOT|dhanvi_clinic|2026-10-23T10:00#dr_rao" and len(row["title"]) <= 24
    assert row["description"] == "Dr. K. Srinivasa Rao · General physician · ₹400"


def test_booking_confirms_emails_family_and_schedules_a_reminder(clinic):
    out = kclinic.book(dict(USER), "dhanvi_clinic", "2026-10-23T12:00#dr_rao")
    assert out["booked"] and out["token"] == 1
    text = clinic["sent"]["text"][0]
    assert "Fri 23 Oct, 12:00 PM" in text and "Token 1" in text and "₹400" in text and "120 minutes before" in text
    assert clinic["sent"]["email"][0][0] == ["amma@example.com", "ravi@example.com"]
    minutes, payload = clinic["sent"]["timers"][0]
    assert round(minutes) == 60 and payload["kind"] == "appointment_reminder"
    record = clinic["records"].items[("dhanvi_clinic", PHONE)]
    assert record["status"]["booking_status"] == "confirmed" and record["status"]["booking_at"] == "2026-10-23T12:00"
    assert record["summary"]["te"][0].startswith("తదుపరి అపాయింట్‌మెంట్")


def test_nobody_gets_the_same_slot_twice(clinic):
    assert kclinic.book(dict(USER), "dhanvi_clinic", "2026-10-23T12:00#dr_rao")["booked"]
    other = dict(USER, phone="+919800000005", name="Someone")
    assert not kclinic.book(other, "dhanvi_clinic", "2026-10-23T12:00#dr_rao")["booked"]
    assert clinic["sent"]["text"][-1].startswith("✅")  # only the first booking was confirmed
    assert clinic["sent"]["list"]  # the second person got fresh times instead
    assert kclinic.free_slots("dhanvi_clinic", kclinic.match_doctors("dhanvi_clinic", ""))[0]["slot_id"] != ""


def test_invalid_or_past_slots_are_refused(clinic):
    assert not kclinic.book(dict(USER), "dhanvi_clinic", "2026-10-23T10:05#dr_rao")["booked"]   # not a slot
    assert not kclinic.book(dict(USER), "dhanvi_clinic", "2026-10-22T10:00#dr_rao")["booked"]   # in the past
    assert not kclinic.book(dict(USER), "dhanvi_clinic", "2026-10-23T11:00#dr_nobody")["booked"]


def test_only_the_patient_can_cancel(clinic):
    kclinic.book(dict(USER), "dhanvi_clinic", "2026-10-23T12:00#dr_rao")
    assert not kclinic.cancel(dict(USER, phone="+919800000005"), "dhanvi_clinic", "2026-10-23T12:00#dr_rao")["cancelled"]
    assert kclinic.cancel(dict(USER), "dhanvi_clinic", "2026-10-23T12:00#dr_rao")["cancelled"]
    assert clinic["records"].items[("dhanvi_clinic", PHONE)]["status"]["booking_status"] == "none"


def test_reminder_has_going_and_cancel_buttons(clinic):
    kclinic.book(dict(USER), "dhanvi_clinic", "2026-10-23T12:00#dr_rao")
    assert kclinic.send_reminder({"business_id": "dhanvi_clinic", "slot_id": "2026-10-23T12:00#dr_rao"})["channel"] == "whatsapp"
    body, buttons = clinic["sent"]["buttons"][0]
    assert "Dr. K. Srinivasa Rao" in body and buttons[1][0] == "APPT|cancel|dhanvi_clinic|2026-10-23T12:00#dr_rao"
    kclinic.cancel(dict(USER), "dhanvi_clinic", "2026-10-23T12:00#dr_rao")
    assert kclinic.send_reminder({"business_id": "dhanvi_clinic", "slot_id": "2026-10-23T12:00#dr_rao"})["skipped"]


def test_clinic_scam_is_still_caught(clinic):
    kclinic.book(dict(USER), "dhanvi_clinic", "2026-10-23T12:00#dr_rao")
    record = clinic["records"].items[("dhanvi_clinic", PHONE)]
    check = kb.verify("dhanvi_clinic", kc.to_jsonable(record), "Dhanvi Clinic: pay Rs 500 advance to confirm your "
                      "appointment, else your booking will be cancelled. UPI dhanvi.desk@ybl", ev.extract(
                          "UPI dhanvi.desk@ybl Rs 500"))
    rules = {f["rule"] for f in kb.red_flags(check)}
    assert {"against_business_policy", "contradicts_records", "unofficial_channel"} <= rules


def test_book_appointment_button_sends_times(clinic):
    kb.perform_action(dict(USER), "dhanvi_clinic", "book")
    assert clinic["sent"]["list"] and clinic["sent"]["text"] == []


class FakeAgent:
    def __init__(self, act):
        self.act, self.messages = act, []

    def __call__(self, prompt):
        self.messages.append({"role": "user", "content": [{"text": prompt}]})
        self.act()
        return "Here are Dr. Lakshmi's free times. Tap one in the list I'm sending."


def test_agent_finds_slots_and_returns_a_list_without_a_verdict(clinic, monkeypatch):
    saved = []
    monkeypatch.setattr(main, "save_verdict", lambda *a, **k: saved.append(a))
    monkeypatch.setattr(main, "get_session_manager", lambda *_a: None)
    monkeypatch.setattr(main, "make_agent", lambda *_a: FakeAgent(lambda: everyday.find_appointment_slots("knee pain")))
    out = main.invoke({"prompt": "User's message:\nI need to see a doctor for my knee pain", "user": dict(USER)})
    assert out["list"]["sections"][0]["rows"][0]["description"].startswith("Dr. P. Lakshmi")
    assert out["buttons"] == [] and saved == []


def test_inbound_lambda_books_on_tap_and_sends_lists(clinic, monkeypatch):
    import app

    taps = []
    monkeypatch.setattr(app.kclinic, "handle_tap", lambda user, payload: taps.append(payload))
    app.handle_choice(PHONE, dict(USER), None, "SLOT|dhanvi_clinic|2026-10-23T12:00#dr_rao")
    app.handle_choice(PHONE, dict(USER, status="stopped"), None, "SLOT|dhanvi_clinic|2026-10-23T12:20#dr_rao")
    assert taps == ["SLOT|dhanvi_clinic|2026-10-23T12:00#dr_rao"]
    app.send_buttons(PHONE, {"list": kclinic.slot_list("dhanvi_clinic", [], "en")})
    assert clinic["sent"]["list"]
