"""SOS: "HELP", "SOS", "panic", "బచావో", "बचाओ" alerts the family at once, then sends them the person's location.

WhatsApp doesn't let a business read a phone's location, so Kavach asks for it with WhatsApp's own
"Send location" button and forwards it to the family the moment it arrives: a map pin, plus a Google Maps link
in the alert (which also reaches family who haven't messaged Kavach in 24 hours, through the approved template)
and in the email. WhatsApp business accounts can't receive live location, so the person is asked for their
current location instead.

The family alert goes out before the location: speed first. Escalation (5 and 10 minutes) is the same as any
family alert, and "I'm safe now" tells the family and stops it. Plain code, no model, so it takes seconds.
"""
from __future__ import annotations

import html
import re
import time

import kavach_common as kc

SOS_WINDOW_SECONDS = 60 * 60       # a location shared within an hour of SOS goes to the family
RECENT_LOCATION_SECONDS = 30 * 60  # a location shared just before SOS goes out with the first alert
ESCALATION_MINUTES = 5

SOS_WORDS = {"help", "sos", "panic", "emergency", "bachao", "bachaao", "bachavo", "బచావో", "కాపాడండి", "కాపాడు",
             "సహాయం", "సాయం", "ప్రమాదం", "ఎమర్జెన్సీ", "मदद", "बचाओ", "बचाइए", "बचाओं", "इमरजेंसी", "आपातकाल"}
FILLER = {"me", "please", "pls", "plz", "now", "urgent", "i", "need", "needed", "quick", "quickly", "fast", "asap",
          "చేయండి", "చెయ్యండి", "కావాలి", "త్వరగా", "నాకు", "నన్ను", "करो", "कीजिए", "चाहिए", "करें", "जल्दी",
          "मुझे", "मेरी"}

T = {
    "sent": {"en": "🆘 I've alerted {names}. They'll call you.\nIf you're in danger right now, call 112 (police, "
                   "ambulance).",
             "te": "🆘 {names}కు హెచ్చరిక పంపాను. వారు మీకు కాల్ చేస్తారు.\nఇప్పుడు ప్రమాదంలో ఉంటే 112కు కాల్ చేయండి "
                   "(పోలీస్, అంబులెన్స్).",
             "hi": "🆘 मैंने {names} को अलर्ट भेज दिया है। वे आपको कॉल करेंगे।\nअभी ख़तरे में हैं तो 112 पर कॉल करें "
                   "(पुलिस, एम्बुलेंस)।"},
    "not_reached": {"en": "⚠️ I couldn't reach {names} on WhatsApp. Please call them yourself.",
                    "te": "⚠️ {names}కు WhatsApp హెచ్చరిక చేరలేదు. దయచేసి మీరే వారికి కాల్ చేయండి.",
                    "hi": "⚠️ {names} तक WhatsApp अलर्ट नहीं पहुँचा। कृपया आप ख़ुद उन्हें कॉल करें।"},
    "no_family": {"en": "🆘 No family member is added yet, so I can't alert anyone. If you're in danger, call 112 "
                        "now. To add family, send MENU.",
                  "te": "🆘 ఇంకా కుటుంబ సభ్యులను చేర్చలేదు, కాబట్టి ఎవరికీ హెచ్చరిక పంపలేను. ప్రమాదంలో ఉంటే ఇప్పుడే 112కు "
                        "కాల్ చేయండి. కుటుంబ సభ్యులను చేర్చడానికి MENU పంపండి.",
                  "hi": "🆘 अभी कोई परिवार सदस्य नहीं जोड़ा गया है, इसलिए किसी को अलर्ट नहीं भेज सकता। ख़तरे में हैं तो "
                        "अभी 112 पर कॉल करें। परिवार जोड़ने के लिए MENU भेजें।"},
    "ask_location": {"en": "📍 Tap *Send location* so your family can see where you are.",
                     "te": "📍 మీరు ఎక్కడ ఉన్నారో మీ కుటుంబానికి తెలియాలంటే *Send location* నొక్కండి.",
                     "hi": "📍 परिवार को आपकी जगह दिखे, इसके लिए *Send location* दबाएँ।"},
    "location_sent": {"en": "📍 Sent your location to {names}.", "te": "📍 మీ లొకేషన్‌ను {names}కు పంపాను.",
                      "hi": "📍 आपकी लोकेशन {names} को भेज दी।"},
    "live_location": {"en": "Live location can't reach Kavach. Please tap 📎 (or +) → Location → *Send your current "
                            "location*.",
                      "te": "లైవ్ లొకేషన్ కవచ్‌కు చేరదు. 📎 (లేదా +) → Location → *Send your current location* "
                            "నొక్కండి.",
                      "hi": "लाइव लोकेशन कवच तक नहीं पहुँचती। 📎 (या +) → Location → *Send your current location* "
                            "दबाएँ।"},
    "btn_safe": {"en": "I'm safe now", "te": "నేను క్షేమం", "hi": "मैं सुरक्षित हूँ"},
    "safe_done": {"en": "✅ Good. I've told {names} that you are safe.",
                  "te": "✅ మంచిది. మీరు క్షేమంగా ఉన్నారని {names}కు చెప్పాను.",
                  "hi": "✅ अच्छा। मैंने {names} को बता दिया कि आप सुरक्षित हैं।"},
    "safe_none": {"en": "✅ Good. Stay safe.", "te": "✅ మంచిది. జాగ్రత్తగా ఉండండి.", "hi": "✅ अच्छा। सुरक्षित रहें।"},
    "offer_share": {"en": "Send this location to your family?", "te": "ఈ లొకేషన్‌ను మీ కుటుంబానికి పంపాలా?",
                    "hi": "यह लोकेशन परिवार को भेजें?"},
    "btn_share": {"en": "Send to family", "te": "కుటుంబానికి పంపు", "hi": "परिवार को भेजें"},
    "btn_no": {"en": "No", "te": "వద్దు", "hi": "नहीं"},
    "expired": {"en": "That has expired. Send HELP if you need your family now.",
                "te": "దాని గడువు ముగిసింది. ఇప్పుడు కుటుంబం కావాలంటే HELP పంపండి.",
                "hi": "यह पुराना हो गया। अभी परिवार की ज़रूरत हो तो HELP भेजें।"},
    "not_set_up": {"en": "🆘 If you're in danger, call 112 now.", "te": "🆘 ప్రమాదంలో ఉంటే ఇప్పుడే 112కు కాల్ చేయండి.",
                   "hi": "🆘 ख़तरे में हैं तो अभी 112 पर कॉल करें।"},
}


def _t(key: str, lang: str | None, **kw) -> str:
    text = T[key].get(lang or "en") or T[key]["en"]
    return text.format(**kw) if kw else text


def _lang(user: dict) -> str:
    return user.get("language") if user.get("language") in ("en", "te", "hi") else "en"


def maps_link(lat: float, lng: float) -> str:
    return f"https://maps.google.com/?q={float(lat):.6f},{float(lng):.6f}"


def is_sos(text: str | None, forwarded: bool = False) -> bool:
    """"HELP", "sos!!", "please help me now", "బచావో", "मदद करो": a short cry for help typed by the person.
    Longer messages ("help me check this link") go to the scam check as usual."""
    if forwarded or not text:
        return False
    words = re.sub(r"[!?.,;:\"'()।*_~🆘]+", " ", text.lower()).split()
    return 0 < len(words) <= 6 and all(w in SOS_WORDS or w in FILLER for w in words) and any(w in SOS_WORDS for w in words)


# =========================================================================== sending

def wa_location(to: str, lat: float, lng: float, name: str = "", address: str = "") -> None:
    loc = {"latitude": float(lat), "longitude": float(lng)}
    if name:
        loc["name"] = name[:100]
    if address:
        loc["address"] = address[:200]
    kc.wa_send({"to": kc.normalize_phone(to), "type": "location", "location": loc})


def wa_location_request(to: str, body: str) -> None:
    kc.wa_send({"to": kc.normalize_phone(to), "recipient_type": "individual", "type": "interactive",
                "interactive": {"type": "location_request_message", "body": {"text": body[:1024]},
                                "action": {"name": "send_location"}}})


def _remember(phone: str, **fields) -> None:
    """Update only these fields on the user's record (safe from the agent, whose user dict is partial)."""
    names = {f"#{k}": k for k in fields}
    kc.table("users_table").update_item(
        Key={"phone": kc.normalize_phone(phone)},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues={f":{k}": kc.clean_for_dynamo(v) for k, v in fields.items()},
    )


def _names(results: list[dict], ok: bool) -> list[str]:
    return [r["name"] for r in results if bool(r["ok"]) is ok]


def _email_family(user: dict, subject: str, body_html: str, text: str) -> None:
    emails = [g["email"] for g in user.get("guardians", []) if g.get("email")]
    if emails:
        kc.email_send(emails, subject, kc.email_shell(subject, body_html), text)


def _pins(user: dict, lat: float, lng: float, when: str) -> None:
    """A native map pin for family inside WhatsApp's 24-hour window (others get the Maps link in the alert)."""
    name = user.get("name") or "Your family member"
    for g in user.get("guardians", []):
        phone = kc.normalize_phone(g.get("phone", ""))
        if phone and kc.in_window(phone):
            try:
                wa_location(phone, lat, lng, f"{name} (Kavach SOS)", f"Shared at {when}")
            except Exception as exc:
                print(f"SOS pin to {phone} failed: {exc!r}")


def start(user: dict, reason: str = "pressed SOS on Kavach and needs help now") -> dict:
    """Alert the family now (with the last location if it is fresh), ask for the location, offer "I'm safe now"."""
    lang = _lang(user)
    phone = kc.normalize_phone(user["phone"])
    guardians = [g for g in user.get("guardians", []) if g.get("phone")]
    last = user.get("last_location") or {}
    fresh = last if int(last.get("at", 0)) >= time.time() - RECENT_LOCATION_SECONDS else None
    what = reason + (f". Location: {maps_link(fresh['lat'], fresh['lng'])}" if fresh else "")

    incident = kc.put_incident({"phone": phone, "name": user.get("name", ""), "type": "sos", "severity": "critical",
                                "summary": what, "district": user.get("district", ""),
                                "family_status": "alerted" if guardians else "no_family"})
    incident_id = incident["incident_id"]
    sos = {"incident_id": incident_id, "until": int(time.time()) + SOS_WINDOW_SECONDS}
    user["sos"] = sos
    _remember(phone, sos=sos)

    if not guardians:
        kc.wa_text(phone, _t("no_family", lang))
        return {"incident_id": incident_id, "alerted": [], "not_reached": []}

    kc.alert_guardians(user, incident_id, what)
    results = [dict(r) for r in kc.LAST_ALERT_RESULTS]
    if fresh:
        _pins(user, fresh["lat"], fresh["lng"], kc.now_ist_str())
    name = html.escape(user.get("name") or "Your family member")
    link = maps_link(fresh["lat"], fresh["lng"]) if fresh else ""
    _email_family(user, f"SOS from {user.get('name') or phone}",
                  f"<p style='font-size:16px'><strong>{name}</strong> pressed SOS on Kavach and needs help now.</p>"
                  f"<p>Call them: <a href='tel:{phone}'>{phone}</a></p>"
                  + (f"<p>Location: <a href='{link}'>{link}</a></p>" if link else
                     "<p>Kavach has asked for their location and will email it as soon as they share it.</p>"),
                  f"{user.get('name') or phone} pressed SOS on Kavach. Call {phone}. {link}")
    kc.append_incident_event(incident_id, "SOS: family alerted: " + (", ".join(_names(results, True)) or "none")
                             + ("; not reached: " + ", ".join(_names(results, False)) if _names(results, False) else ""))
    try:
        kc.schedule_once(f"kavach-esc-{incident_id}", ESCALATION_MINUTES,
                         {"kind": "family_escalation", "incident_id": incident_id, "step": 1})
    except Exception as exc:
        print(f"SOS escalation not scheduled: {exc!r}")

    reached, missed = _names(results, True), _names(results, False)
    lines = []
    if reached:
        lines.append(_t("sent", lang, names=", ".join(reached)))
    if missed:
        lines.append(_t("not_reached", lang, names=", ".join(missed)))
        if not reached:
            lines.append(_t("not_set_up", lang))
    kc.wa_buttons(phone, "\n".join(lines), [(f"SOS|safe|{incident_id}", _t("btn_safe", lang))])
    if not fresh:
        try:
            wa_location_request(phone, _t("ask_location", lang))
        except Exception as exc:  # older WhatsApp clients: plain text still explains how
            print(f"Location request not sent: {exc!r}")
            kc.wa_text(phone, _t("live_location", lang))
    return {"incident_id": incident_id, "alerted": reached, "not_reached": missed}


def share_location(user: dict, incident_id: str, lat: float, lng: float, label: str = "",
                   for_sos: bool = True) -> list[str]:
    """Send this location to every family member: a pin (inside the 24-hour window) and the alert with a
    Maps link (template outside it), plus an email."""
    link = maps_link(lat, lng)
    when = kc.now_ist_str()
    what = (f"shared their location {'for the SOS ' if for_sos else 'with you '}({when}): {link}"
            + (f" ({label})" if label else ""))
    _pins(user, lat, lng, when)
    kc.alert_guardians(user, incident_id, what)
    results = [dict(r) for r in kc.LAST_ALERT_RESULTS]
    name = html.escape(user.get("name") or "Your family member")
    _email_family(user, f"Location from {user.get('name') or user['phone']} (Kavach SOS)",
                  f"<p><strong>{name}</strong> shared their location at {html.escape(when)}.</p>"
                  f"<p><a href='{link}'>Open in Google Maps</a>" + (f" ({html.escape(label)})" if label else "")
                  + f"</p><p>Call them: <a href='tel:{user['phone']}'>{user['phone']}</a></p>",
                  f"{user.get('name') or user['phone']} shared their location: {link}")
    try:
        if for_sos:  # the 5-minute re-alert repeats the summary, so it carries the location from now on
            kc.update_incident(incident_id, summary=f"pressed SOS on Kavach and needs help now. Location: {link}")
        kc.update_incident(incident_id, location={"lat": float(lat), "lng": float(lng), "label": label,
                                                  "at": kc.now_iso()})
        kc.append_incident_event(incident_id, f"Location shared with family: {link}")
    except Exception as exc:
        print(f"Incident not updated with location: {exc!r}")
    return _names(results, True)


# =========================================================================== entry points (inbound Lambda)

def active_sos(user: dict) -> dict | None:
    sos = user.get("sos") or {}
    return sos if sos.get("incident_id") and int(sos.get("until", 0)) >= time.time() else None


def handle_location(user: dict, location: dict) -> bool:
    """A location the person shared: to the family at once during an SOS, otherwise offer to send it."""
    try:
        lat, lng = float(location["latitude"]), float(location["longitude"])
    except (KeyError, TypeError, ValueError):
        return False
    lang = _lang(user)
    label = " ".join(x for x in (location.get("name"), location.get("address")) if x)[:150]
    user["last_location"] = {"lat": lat, "lng": lng, "label": label, "at": int(time.time())}
    _remember(user["phone"], last_location=user["last_location"])
    sos = active_sos(user)
    if sos:
        reached = share_location(user, sos["incident_id"], lat, lng, label)
        kc.wa_text(user["phone"], _t("location_sent", lang, names=", ".join(reached)) if reached
                   else _t("not_reached", lang, names=", ".join(g.get("name", "") for g in user.get("guardians", []))))
        return True
    if user.get("guardians"):
        kc.wa_buttons(user["phone"], _t("offer_share", lang),
                      [("SOS|share|-", _t("btn_share", lang)), ("SOS|noshare|-", _t("btn_no", lang))])
        return True
    return False


def handle_unsupported(user: dict, message: dict) -> bool:
    """Live location arrives as an unsupported message; during an SOS, explain how to send the location."""
    if active_sos(user):
        kc.wa_text(user["phone"], _t("live_location", _lang(user)))
        return True
    return False


def handle_tap(user: dict, choice: str) -> None:
    """SOS|safe|<incident>, SOS|share|-, SOS|noshare|-"""
    parts = choice.split("|")
    action, incident_id = (parts + ["", ""])[1], (parts + ["", "", ""])[2]
    lang = _lang(user)
    phone = user["phone"]
    if action == "safe":
        sos = user.get("sos") or {}
        if sos.get("incident_id") != incident_id:
            kc.wa_text(phone, _t("safe_none", lang))
            return
        user.pop("sos", None)
        _remember(phone, sos={})
        kc.update_incident(incident_id, family_status="resolved", resolved_by="person")
        kc.append_incident_event(incident_id, "Person tapped I'm safe now")
        kc.alert_guardians(user, incident_id, "says they are safe now. The SOS is cancelled, no need to worry")
        reached = _names(kc.LAST_ALERT_RESULTS, True)
        _email_family(user, f"{user.get('name') or phone} is safe now",
                      f"<p>{html.escape(user.get('name') or phone)} tapped \"I'm safe now\" on Kavach. "
                      "The SOS is cancelled.</p>", f"{user.get('name') or phone} is safe now. The SOS is cancelled.")
        kc.wa_text(phone, _t("safe_done", lang, names=", ".join(reached)) if reached else _t("safe_none", lang))
    elif action == "share":
        last = user.get("last_location") or {}
        if not last or int(last.get("at", 0)) < time.time() - RECENT_LOCATION_SECONDS:
            kc.wa_text(phone, _t("expired", lang))
            return
        incident = kc.put_incident({"phone": kc.normalize_phone(phone), "name": user.get("name", ""),
                                    "type": "location_share", "severity": "info",
                                    "summary": "shared their location", "family_status": "resolved"})
        reached = share_location(user, incident["incident_id"], last["lat"], last["lng"], last.get("label", ""),
                                 for_sos=False)
        kc.wa_text(phone, _t("location_sent", lang, names=", ".join(reached)) if reached
                   else _t("not_reached", lang, names=", ".join(g.get("name", "") for g in user.get("guardians", []))))
    else:
        kc.wa_text(phone, "👍")
