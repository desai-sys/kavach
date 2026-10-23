"""Doctor appointments at a Kavach member clinic.

  find a slot   -> free_slots(): the clinic's sessions for the next few days, minus booked slots
  pick it       -> a WhatsApp list message; tapping a row sends SLOT|<clinic>|<slot id>
  book it       -> book(): a conditional write, so two people can never get the same slot
  confirm it    -> WhatsApp to the person, email (SES) to them and their family
  remind them   -> EventBridge Scheduler fires the escalation Lambda before the visit (send_reminder)

Booking is plain code (no model): the agent only finds slots and shows them; the person's tap books.
The clinic in businesses.json (Dhanvi Family Clinic) is fictional.
"""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

import kavach_business as kb
import kavach_common as kc

DAYS_AHEAD = 3          # open days to offer
LOOK_AHEAD_DAYS = 10    # calendar days searched to find them
MAX_ROWS = 10
MIN_LEAD_MINUTES = 30

STRINGS = {
    "list_body": {
        "en": "Pick a time at {name}. The fee is paid at the clinic after the visit; no advance.",
        "te": "{name}లో మీకు అనుకూలమైన సమయం ఎంచుకోండి. ఫీజు డాక్టర్‌ను కలిసిన తర్వాత క్లినిక్‌లో చెల్లించాలి; అడ్వాన్స్ లేదు.",
        "hi": "{name} में अपना समय चुनें। फ़ीस विज़िट के बाद क्लिनिक में दी जाती है; कोई एडवांस नहीं।",
    },
    "list_button": {"en": "Choose a time", "te": "సమయం ఎంచుకోండి", "hi": "समय चुनें"},
    "no_slots": {
        "en": "{name} has no free times in the next {days} days. Tap Call me back and the clinic will fit you in.",
        "te": "రాబోయే {days} రోజుల్లో {name}లో ఖాళీ సమయం లేదు. 'నాకు కాల్ చేయండి' నొక్కితే క్లినిక్ వాళ్లు మీకు సమయం ఇస్తారు.",
        "hi": "अगले {days} दिनों में {name} में कोई समय खाली नहीं है। 'मुझे कॉल करें' दबाएँ, क्लिनिक आपको समय देगा।",
    },
    "booked": {
        "en": "✅ Appointment booked at {name}\n• {doctor} ({specialty})\n• {when}\n• Token {token}\n• {address}\n"
              "Pay ₹{fee} at the reception after your visit. {short} never asks for advance payment.\n{remind}",
        "te": "✅ {name}లో అపాయింట్‌మెంట్ బుక్ అయింది\n• {doctor} ({specialty})\n• {when}\n• టోకెన్ {token}\n• {address}\n"
              "డాక్టర్‌ను కలిసిన తర్వాత రిసెప్షన్‌లో ₹{fee} చెల్లించండి. {short} ఎప్పుడూ ముందుగా డబ్బు అడగదు.\n{remind}",
        "hi": "✅ {name} में अपॉइंटमेंट बुक हो गया\n• {doctor} ({specialty})\n• {when}\n• टोकन {token}\n• {address}\n"
              "विज़िट के बाद रिसेप्शन पर ₹{fee} दें। {short} कभी पहले से पैसे नहीं माँगता।\n{remind}",
    },
    "remind_note": {
        "en": "I'll remind you {minutes} minutes before.",
        "te": "{minutes} నిమిషాల ముందు గుర్తు చేస్తాను.",
        "hi": "मैं {minutes} मिनट पहले याद दिलाऊँगा।",
    },
    "taken": {
        "en": "Sorry, that time was just taken or has passed. Please pick another:",
        "te": "క్షమించండి, ఆ సమయం ఇప్పుడే బుక్ అయింది లేదా గడిచిపోయింది. దయచేసి వేరే సమయం ఎంచుకోండి:",
        "hi": "माफ़ कीजिए, वह समय अभी बुक हो गया या निकल गया। कृपया दूसरा समय चुनें:",
    },
    "reminder": {
        "en": "⏰ Reminder: your appointment with {doctor} at {name} is at {when} (token {token}). {address}.",
        "te": "⏰ గుర్తు: {when}కి {name}లో {doctor} గారితో మీ అపాయింట్‌మెంట్ ఉంది (టోకెన్ {token}). {address}.",
        "hi": "⏰ याद दिलाना: {when} बजे {name} में {doctor} के साथ आपका अपॉइंटमेंट है (टोकन {token})। {address}।",
    },
    "going": {"en": "I'm on my way", "te": "బయలుదేరుతున్నా", "hi": "मैं निकल रहा हूँ"},
    "cancel_btn": {"en": "Cancel visit", "te": "రద్దు చేయండి", "hi": "रद्द करें"},
    "going_ok": {
        "en": "👍 Safe travels. Show token {token} at the reception.",
        "te": "👍 జాగ్రత్తగా వెళ్ళండి. రిసెప్షన్‌లో టోకెన్ {token} చూపించండి.",
        "hi": "👍 आराम से जाइए। रिसेप्शन पर टोकन {token} दिखाएँ।",
    },
    "cancelled": {
        "en": "Cancelled your {when} appointment with {doctor}. The time is free for someone else now.",
        "te": "{when} {doctor} గారితో మీ అపాయింట్‌మెంట్ రద్దు చేశాను. ఆ సమయం ఇప్పుడు వేరేవారికి అందుబాటులో ఉంది.",
        "hi": "{when} का {doctor} के साथ आपका अपॉइंटमेंट रद्द कर दिया। वह समय अब किसी और के लिए खाली है।",
    },
    "not_found": {
        "en": "I couldn't find that appointment. It may have been cancelled already.",
        "te": "ఆ అపాయింట్‌మెంట్ దొరకలేదు. ఇప్పటికే రద్దు అయి ఉండవచ్చు.",
        "hi": "वह अपॉइंटमेंट नहीं मिला। शायद पहले ही रद्द हो चुका है।",
    },
}


def _t(key: str, lang: str | None, **kw) -> str:
    options = STRINGS[key]
    return (options.get(lang or "en") or options["en"]).format(**kw)


def _lang(user: dict) -> str:
    return user.get("language") if user.get("language") in kb.LANGS else "en"


def _now() -> datetime:
    return datetime.now(kc.IST).replace(tzinfo=None, second=0, microsecond=0)


def clinic_ids() -> list[str]:
    return [bid for bid, p in kb.PROFILES.items() if p.get("kind") == "clinic"]


def doctor(business_id: str, doctor_id: str) -> dict | None:
    return next((d for d in kb.PROFILES[business_id].get("doctors", []) if d["id"] == doctor_id), None)


def match_doctors(business_id: str, concern: str = "") -> list[dict]:
    """The doctor(s) whose keywords best match the concern; the first (general) doctor if nothing matches."""
    docs = kb.PROFILES[business_id].get("doctors", [])
    c = (concern or "").lower()
    scores = [(sum(1 for k in d.get("keywords", []) if k.lower() in c)
               + 2 * (d["specialty"].lower().split(" (")[0] in c or d["name"].lower() in c), d) for d in docs]
    best = max((score for score, _d in scores), default=0)
    return [d for score, d in scores if score == best] if best else docs[:1]


def when_text(slot_dt: datetime) -> str:
    return f"{slot_dt:%a} {slot_dt.day} {slot_dt:%b}, {slot_dt:%I:%M %p}".replace(", 0", ", ")


def parse_slot(slot_id: str) -> tuple[datetime | None, str]:
    stamp, _, doctor_id = (slot_id or "").partition("#")
    try:
        return datetime.fromisoformat(stamp), doctor_id
    except ValueError:
        return None, doctor_id


def _sessions(doc: dict, day: date) -> list[datetime]:
    if day.weekday() not in doc.get("days", []):
        return []
    out = []
    for start, end in doc.get("sessions", []):
        t = datetime.combine(day, datetime.strptime(start, "%H:%M").time())
        stop = datetime.combine(day, datetime.strptime(end, "%H:%M").time())
        while t < stop:
            out.append(t)
            t += timedelta(minutes=doc.get("slot_minutes", 20))
    return out


def _booked(business_id: str, start: date, end: date) -> set[str]:
    resp = kc.table("bookings_table").query(KeyConditionExpression=Key("business_id").eq(business_id)
                                            & Key("slot_id").between(f"{start}T00:00", f"{end}T23:59~"))
    return {item["slot_id"] for item in resp.get("Items", [])}


def free_slots(business_id: str, doctors: list[dict], now: datetime | None = None, days: int = DAYS_AHEAD,
               limit: int = MAX_ROWS) -> list[dict]:
    now = now or _now()
    taken = _booked(business_id, now.date(), now.date() + timedelta(days=LOOK_AHEAD_DAYS))
    slots, open_days = [], 0
    for offset in range(LOOK_AHEAD_DAYS):
        day = now.date() + timedelta(days=offset)
        found = 0
        for doc in doctors:
            for t in _sessions(doc, day):
                slot_id = f"{t:%Y-%m-%dT%H:%M}#{doc['id']}"
                if t >= now + timedelta(minutes=MIN_LEAD_MINUTES) and slot_id not in taken:
                    slots.append({"slot_id": slot_id, "when": when_text(t), "doctor": doc["name"],
                                  "specialty": doc["specialty"], "fee": doc["fee"], "at": t})
                    found += 1
        open_days += 1 if found else 0
        if open_days >= days:
            break
    slots.sort(key=lambda s: s["at"])
    # Spread the choice: at most 4 rows per day so later days show up too.
    per_day: dict[date, int] = {}
    picked = []
    for s in slots:
        if per_day.get(s["at"].date(), 0) < 4:
            per_day[s["at"].date()] = per_day.get(s["at"].date(), 0) + 1
            picked.append(s)
    return picked[:limit]


def slot_list(business_id: str, slots: list[dict], lang: str) -> dict:
    """The WhatsApp list message for these slots (sent by the inbound Lambda or here)."""
    name = kb.PROFILES[business_id]["name"]
    return {
        "body": _t("list_body", lang, name=name),
        "button": _t("list_button", lang),
        "header": name,
        "sections": [{"title": "Free times", "rows": [
            {"id": f"SLOT|{business_id}|{s['slot_id']}", "title": s["when"],
             "description": f"{s['doctor']} · {s['specialty'].split(' (')[0]} · ₹{s['fee']}"} for s in slots]}],
    }


def send_slot_list(user: dict, business_id: str, concern: str = "", prefix: str = "") -> str:
    lang = _lang(user)
    slots = free_slots(business_id, match_doctors(business_id, concern))
    name = kb.PROFILES[business_id]["name"]
    if not slots:
        text = _t("no_slots", lang, name=name, days=DAYS_AHEAD)
        kc.wa_text(user["phone"], (prefix + "\n" if prefix else "") + text)
        return text
    lst = slot_list(business_id, slots, lang)
    if prefix:
        lst["body"] = prefix + "\n" + lst["body"]
    kc.wa_list(user["phone"], lst["body"], lst["button"], lst["sections"], header=lst["header"])
    return lst["body"]


# ----------------------------------------------------------------------------- book, cancel, remind

def book(user: dict, business_id: str, slot_id: str) -> dict:
    """Book a slot for this person (looked up by their own number). Two taps can never get the same slot."""
    lang = _lang(user)
    phone = kc.normalize_phone(user.get("phone", ""))
    p = kb.PROFILES.get(business_id)
    slot_dt, doctor_id = parse_slot(slot_id)
    doc = doctor(business_id, doctor_id) if p else None
    valid = bool(p and doc and slot_dt and slot_dt >= _now() + timedelta(minutes=10)
                 and slot_dt in _sessions(doc, slot_dt.date()))
    if valid:
        token = 1 + sum(1 for s in _booked(business_id, slot_dt.date(), slot_dt.date()) if s.endswith(f"#{doctor_id}"))
        try:
            kc.table("bookings_table").put_item(
                Item=kc.clean_for_dynamo({"business_id": business_id, "slot_id": slot_id, "phone": phone,
                                          "name": user.get("name", ""), "doctor_id": doctor_id, "token": token,
                                          "created_at": kc.now_iso(), "status": "booked"}),
                ConditionExpression="attribute_not_exists(slot_id)")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            valid = False
    if not valid:
        if p:
            send_slot_list(user, business_id, doc["specialty"] if doc else "", prefix=_t("taken", lang))
        return {"booked": False}

    when = when_text(slot_dt)
    minutes = int(p.get("reminder_minutes_before", 120))
    lead = (slot_dt - _now()).total_seconds() / 60
    remind_in = lead - minutes if lead - minutes >= 2 else (lead - 30 if lead - 30 >= 2 else None)
    reminded_before = minutes if lead - minutes >= 2 else 30
    if remind_in is not None:
        try:
            kc.schedule_once(f"kavach-appt-{business_id}", remind_in,
                             {"kind": "appointment_reminder", "business_id": business_id, "slot_id": slot_id})
        except Exception as exc:
            print(f"Reminder not scheduled: {exc!r}")
            remind_in = None
    remind = _t("remind_note", lang, minutes=reminded_before) if remind_in is not None else ""
    text = _t("booked", lang, name=p["name"], short=p["short_name"], doctor=doc["name"], specialty=doc["specialty"],
              when=when, token=token, address=p.get("address", ""), fee=doc["fee"], remind=remind).strip()
    kc.wa_text(phone, text)
    _save_record(business_id, phone, user, add={"slot_id": slot_id, "doctor": doc["name"],
                                                "specialty": doc["specialty"], "token": token, "fee": doc["fee"]})
    _email_family(user, p, doc, when, token)
    try:
        kb.record_signal(business_id, "appointment_booked", district=user.get("district", ""))
    except Exception as exc:
        print(f"Signal not saved: {exc!r}")
    return {"booked": True, "when": when, "doctor": doc["name"], "token": token, "message_sent_to_user": text}


def cancel(user: dict, business_id: str, slot_id: str) -> dict:
    lang = _lang(user)
    phone = kc.normalize_phone(user.get("phone", ""))
    slot_dt, doctor_id = parse_slot(slot_id)
    doc = doctor(business_id, doctor_id) if business_id in kb.PROFILES else None
    try:
        kc.table("bookings_table").delete_item(
            Key={"business_id": business_id, "slot_id": slot_id},
            ConditionExpression="attribute_exists(slot_id) AND #p = :phone",
            ExpressionAttributeNames={"#p": "phone"}, ExpressionAttributeValues={":phone": phone})
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        text = _t("not_found", lang)
        kc.wa_text(phone, text)
        return {"cancelled": False, "message_sent_to_user": text}
    _save_record(business_id, phone, user, remove=slot_id)
    text = _t("cancelled", lang, when=when_text(slot_dt) if slot_dt else "", doctor=doc["name"] if doc else "")
    kc.wa_text(phone, text)
    return {"cancelled": True, "message_sent_to_user": text}


def send_reminder(event: dict) -> dict:
    """Called by the escalation Lambda (EventBridge Scheduler) before the visit."""
    business_id, slot_id = event.get("business_id", ""), event.get("slot_id", "")
    item = kc.table("bookings_table").get_item(Key={"business_id": business_id, "slot_id": slot_id}).get("Item")
    if not item:
        return {"ok": True, "skipped": "cancelled"}
    item = kc.to_jsonable(item)
    user = kc.get_user(item["phone"]) or {"phone": item["phone"], "language": "en", "guardians": []}
    lang = _lang(user)
    p = kb.PROFILES[business_id]
    slot_dt, doctor_id = parse_slot(slot_id)
    doc = doctor(business_id, doctor_id) or {"name": ""}
    text = _t("reminder", lang, doctor=doc["name"], name=p["name"], when=when_text(slot_dt), token=item.get("token"),
              address=p.get("address", ""))
    try:  # buttons work inside WhatsApp's 24-hour window
        kc.wa_buttons(item["phone"], text, [(f"APPT|going|{business_id}|{slot_id}", _t("going", lang)),
                                            (f"APPT|cancel|{business_id}|{slot_id}", _t("cancel_btn", lang))])
        return {"ok": True, "channel": "whatsapp"}
    except Exception as exc:
        print(f"WhatsApp reminder failed ({exc!r}); emailing instead")
    emails = [e for e in [user.get("email")] + [g.get("email") for g in user.get("guardians", [])] if e]
    kc.email_send(emails, f"Reminder: appointment at {p['name']}",
                  kc.email_shell("Appointment reminder", f"<p>{html.escape(_t('reminder', 'en', doctor=doc['name'], name=p['name'], when=when_text(slot_dt), token=item.get('token'), address=p.get('address', '')))}</p>"))
    return {"ok": True, "channel": "email"}


def handle_tap(user: dict, payload: str) -> None:
    """SLOT|<clinic>|<slot id>  or  APPT|going|<clinic>|<slot id>  or  APPT|cancel|<clinic>|<slot id>."""
    kind, _, rest = payload.partition("|")
    if kind == "SLOT":
        business_id, _, slot_id = rest.partition("|")
        book(user, business_id, slot_id)
        return
    action, _, rest = rest.partition("|")
    business_id, _, slot_id = rest.partition("|")
    if action == "cancel":
        cancel(user, business_id, slot_id)
    else:
        phone = kc.normalize_phone(user.get("phone", ""))
        item = kc.table("bookings_table").get_item(Key={"business_id": business_id, "slot_id": slot_id}).get("Item")
        if item and kc.normalize_phone(item.get("phone", "")) == phone:
            kc.wa_text(phone, _t("going_ok", _lang(user), token=kc.to_jsonable(item).get("token")))


def upcoming(business_id: str, phone: str) -> list[dict]:
    record = kb.get_record(business_id, phone) or {}
    now = _now()
    out = []
    for a in (record.get("status") or {}).get("appointments", []):
        slot_dt, _ = parse_slot(a.get("slot_id", ""))
        if slot_dt and slot_dt >= now - timedelta(hours=1):
            out.append({**a, "when": when_text(slot_dt)})
    return out


# ----------------------------------------------------------------------------- record and family email

SUMMARY = {
    "next": {"en": "Next appointment: {doctor} ({specialty}), {when}, token {token}.",
             "te": "తదుపరి అపాయింట్‌మెంట్: {doctor} ({specialty}), {when}, టోకెన్ {token}.",
             "hi": "अगला अपॉइंटमेंट: {doctor} ({specialty}), {when}, टोकन {token}।"},
    "none": {"en": "No upcoming appointment.", "te": "రాబోయే అపాయింట్‌మెంట్ ఏదీ లేదు.",
             "hi": "कोई आने वाला अपॉइंटमेंट नहीं है।"},
    "fee": {"en": "Fees are paid at the reception after the visit. No advance is ever needed.",
            "te": "ఫీజు డాక్టర్‌ను కలిసిన తర్వాత రిసెప్షన్‌లో చెల్లించాలి. ఎప్పుడూ అడ్వాన్స్ అవసరం లేదు.",
            "hi": "फ़ीस विज़िट के बाद रिसेप्शन पर दी जाती है। कभी एडवांस नहीं लगता।"},
}


def _save_record(business_id: str, phone: str, user: dict, add: dict | None = None, remove: str | None = None) -> None:
    """Keep the member record in step, so the usual checks work ("your appointment is cancelled, pay ₹500")."""
    try:
        record = kb.get_record(business_id, phone) or {"business_id": business_id, "phone": phone, "status": {}}
    except Exception as exc:
        print(f"Clinic record not read: {exc!r}")
        return
    status = dict(record.get("status") or {})
    appts = [a for a in status.get("appointments", []) if a.get("slot_id") != remove]
    if add:
        appts.append(add)
    now = _now()
    appts = sorted([a for a in appts if (parse_slot(a["slot_id"])[0] or now) >= now - timedelta(hours=1)],
                   key=lambda a: a["slot_id"])
    status.update(appointments=appts, amount_due_now=0, advance_paid=0, refund_pending=False)
    summary = {}
    for lang in kb.LANGS:
        lines = []
        for a in appts[:3]:
            lines.append(SUMMARY["next"][lang].format(doctor=a["doctor"], specialty=a["specialty"].split(" (")[0],
                                                      when=when_text(parse_slot(a["slot_id"])[0]), token=a["token"]))
        summary[lang] = (lines or [SUMMARY["none"][lang]]) + [SUMMARY["fee"][lang]]
    if appts:
        first_dt, _ = parse_slot(appts[0]["slot_id"])
        status.update(booking_status="confirmed", booking_at=f"{first_dt:%Y-%m-%dT%H:%M}",
                      service=f"appointment with {appts[0]['doctor']}")
    else:
        status.update(booking_status="none")
        status.pop("booking_at", None)
    record.update(status=status, summary=summary, customer_name=user.get("name", ""), updated_at=kc.now_iso())
    try:
        kc.table("business_records_table").put_item(Item=kc.clean_for_dynamo(record))
    except Exception as exc:
        print(f"Clinic record not saved: {exc!r}")


def _email_family(user: dict, p: dict, doc: dict, when: str, token) -> None:
    emails = [e for e in [user.get("email")] + [g.get("email") for g in user.get("guardians", [])] if e]
    if not emails:
        return
    who = user.get("name") or "Your family member"
    rows = [("Doctor", f"{doc['name']} ({doc['specialty']})"), ("When", when), ("Token", token),
            ("Where", f"{p['name']}, {p.get('address', '')}"), ("Fee", f"₹{doc['fee']}, paid at the reception after the visit")]
    table = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#78716c'>{html.escape(k)}</td>"
                    f"<td style='padding:4px 0'>{html.escape(str(v))}</td></tr>" for k, v in rows)
    try:
        kc.email_send(emails, f"{who} has a doctor's appointment on {when}",
                      kc.email_shell(f"{html.escape(who)} has an appointment",
                                     f"<table role='presentation'>{table}</table>"
                                     f"<p>Booked on WhatsApp through Kavach. {html.escape(p['short_name'])} never asks "
                                     "for advance payment; anyone asking for money to 'confirm' this visit is a scammer.</p>"),
                      "\n".join(f"{k}: {v}" for k, v in rows))
    except Exception as exc:
        print(f"Family email failed: {exc!r}")
