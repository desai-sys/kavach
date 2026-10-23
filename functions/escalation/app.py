"""Timer-driven follow-ups, invoked once by EventBridge Scheduler.

kind = "family_escalation": nobody tapped "I'm calling" yet -> re-alert and email (step 1),
                            then mark the incident as unanswered and email again (step 2).
kind = "golden_hour_check": 15 minutes after money was lost, ask whether 1930 was called.
kind = "appointment_reminder": before a clinic visit booked through Kavach (kavach_clinic.send_reminder).
"""
from __future__ import annotations

import html

import kavach_common as kc

GH_TEXT = {
    "en": "It has been 15 minutes. Did you call 1930 to report the payment? Reporting quickly helps get the money held.",
    "te": "15 నిమిషాలు అయ్యింది. చెల్లింపు గురించి 1930కి కాల్ చేశారా? త్వరగా ఫిర్యాదు చేస్తే డబ్బు ఆపే అవకాశం ఎక్కువ.",
    "hi": "15 मिनट हो गए हैं। क्या आपने भुगतान की शिकायत के लिए 1930 पर कॉल किया? जल्दी शिकायत करने से पैसा रोके जाने की संभावना बढ़ती है।",
}
GH_BUTTONS = {
    "en": [("called", "Yes, I called"), ("help", "Not yet, help me")],
    "te": [("called", "అవును, చేశాను"), ("help", "ఇంకా లేదు, సహాయం")],
    "hi": [("called", "हाँ, कर दिया"), ("help", "अभी नहीं, मदद करें")],
}


def handler(event, _context):
    kind = event.get("kind")
    if kind == "appointment_reminder":
        import kavach_clinic
        return kavach_clinic.send_reminder(event)
    incident = kc.get_incident(event.get("incident_id", ""))
    if not incident:
        print(f"No incident for {event}")
        return {"ok": False}
    user = kc.get_user(incident["phone"]) or {"phone": incident["phone"], "guardians": []}

    if kind == "family_escalation":
        return family_escalation(incident, user, int(event.get("step", 1)))
    if kind == "golden_hour_check":
        return golden_hour_check(incident, user)
    print(f"Unknown kind {kind}")
    return {"ok": False}


def family_escalation(incident: dict, user: dict, step: int) -> dict:
    if incident.get("family_status") in ("acknowledged", "resolved"):
        print(f"{incident['incident_id']} already {incident['family_status']}, nothing to do")
        return {"ok": True, "skipped": True}

    name = user.get("name") or "Your family member"
    emails = [g["email"] for g in user.get("guardians", []) if g.get("email")]
    if step == 1:
        earlier = incident.get("summary") or "may be in a scam"
        kc.alert_guardians(user, incident["incident_id"],
                           f"still needs help and nobody has confirmed yet. Earlier alert: {name} {earlier}")
        kc.email_send(emails, f"Second alert: nobody has reached {name} yet",
                      kc.email_shell("Nobody has confirmed yet",
                                     f"<p>Kavach alerted the family 5 minutes ago and no one has tapped "
                                     f"\"I'm calling now\".</p><p><strong>{html.escape(name)}</strong> "
                                     f"{html.escape(incident.get('summary', ''))}</p>"
                                     f"<p>Please call <a href='tel:{user['phone']}'>{user['phone']}</a> now.</p>"))
        kc.append_incident_event(incident["incident_id"], "Escalation step 1: guardians re-alerted and emailed")
        kc.schedule_once(f"kavach-esc2-{incident['incident_id']}", 5,
                         {"kind": "family_escalation", "incident_id": incident["incident_id"], "step": 2})
    else:
        kc.update_incident(incident["incident_id"], family_status="unanswered")
        kc.email_send(emails, f"Kavach: alert for {name} is still unanswered",
                      kc.email_shell("Alert still unanswered",
                                     "<p>No family member confirmed within 10 minutes. If you can't reach them, "
                                     "ask a neighbour to check in person. If money was sent, call 1930.</p>"))
        kc.append_incident_event(incident["incident_id"], "Escalation step 2: marked unanswered")
    return {"ok": True, "step": step}


def golden_hour_check(incident: dict, user: dict) -> dict:
    if incident.get("golden_hour_status") == "reported_1930":
        return {"ok": True, "skipped": True}
    lang = user.get("language", "en")
    buttons = [(f"GH|{incident['incident_id']}|{action}", title) for action, title in GH_BUTTONS.get(lang, GH_BUTTONS["en"])]
    try:
        kc.wa_buttons(user["phone"], GH_TEXT.get(lang, GH_TEXT["en"]), buttons)
    except Exception as exc:  # outside the 24-hour window the family template is the fallback
        print(f"Check-in to victim failed: {exc!r}")
        kc.alert_guardians(user, incident["incident_id"], "lost money to a scam 15 minutes ago. Please make sure they call 1930")
    kc.append_incident_event(incident["incident_id"], "15-minute golden-hour check-in sent")
    return {"ok": True}
