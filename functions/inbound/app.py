"""Inbound WhatsApp handler.

End User Messaging Social -> SNS -> this Lambda.

For every customer message it:
  1. de-duplicates (SNS can deliver twice),
  2. runs onboarding (language, consent, guardians) if needed,
  3. handles button taps (family "I'm calling" / "I've reached her", golden-hour check-ins,
     member-business actions such as "My real policy" or "Report this scam",
     the owner's Yes / Cancel for an ops start/stop/reboot),
  3b. sends "aws ..." messages from the owner's number to the ops agent (see kavach_ops.py),
  4. otherwise fetches media to S3, transcribes voice notes, calls the Kavach agent
     on AgentCore Runtime and sends the agent's reply back on WhatsApp, followed by the
     member business's buttons when the message was about one.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

import kavach_business as kb
import kavach_clinic as kclinic
import kavach_common as kc
import kavach_ops as kops

AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
# The agent can take 30-90 s (vision + browser); default boto3 read timeout is 60 s.
# One attempt only, so a slow answer never runs the investigation twice.
AGENTCORE = boto3.client("bedrock-agentcore", config=Config(read_timeout=300, connect_timeout=10,
                                                            retries={"max_attempts": 1}))

LANG_BUTTONS = [("LANG|te", "తెలుగు"), ("LANG|hi", "हिन्दी"), ("LANG|en", "English")]

CONSENT_TEXT = {
    "en": ("Kavach checks messages, links, screenshots and voice notes you forward, and tells you if they are a scam.\n\n"
           "If something looks dangerous, Kavach will alert the family members you add. "
           "Media you send is deleted after 7 days. You can stop any time by sending STOP.\n\nDo you agree?"),
    "te": ("మీరు పంపే మెసేజ్‌లు, లింకులు, స్క్రీన్‌షాట్‌లు, వాయిస్ నోట్‌లను కవచ్ పరిశీలించి, అవి మోసమా కాదా అని చెబుతుంది.\n\n"
           "ప్రమాదం అనిపిస్తే, మీరు చేర్చిన కుటుంబ సభ్యులకు కవచ్ హెచ్చరిక పంపుతుంది. "
           "మీరు పంపిన ఫైల్స్ 7 రోజుల్లో తొలగించబడతాయి. ఎప్పుడైనా STOP అని పంపి ఆపవచ్చు.\n\nమీరు అంగీకరిస్తారా?"),
    "hi": ("आप जो मैसेज, लिंक, स्क्रीनशॉट और वॉइस नोट भेजते हैं, कवच उनकी जाँच करके बताता है कि वे धोखा हैं या नहीं।\n\n"
           "अगर कुछ खतरनाक लगे, तो कवच आपके जोड़े गए परिवार के सदस्यों को अलर्ट भेजेगा। "
           "आपकी भेजी गई फ़ाइलें 7 दिनों में हटा दी जाती हैं। कभी भी STOP भेजकर बंद कर सकते हैं।\n\nक्या आप सहमत हैं?"),
}
CONSENT_BUTTONS = {
    "en": [("CONSENT|yes", "I agree"), ("CONSENT|no", "No thanks")],
    "te": [("CONSENT|yes", "అంగీకరిస్తున్నాను"), ("CONSENT|no", "వద్దు")],
    "hi": [("CONSENT|yes", "सहमत हूँ"), ("CONSENT|no", "नहीं")],
}
WELCOME = {
    "en": ("You're protected. 🛡️ Forward me anything that looks suspicious: a message, link, screenshot, PDF or voice note.\n\n"
           "To add a family member who should be alerted, send:\nGUARDIAN Ravi +919876543210 ravi@example.com"),
    "te": ("మీకు రక్షణ ప్రారంభమైంది. 🛡️ అనుమానంగా అనిపించే ఏదైనా నాకు ఫార్వర్డ్ చేయండి: మెసేజ్, లింక్, స్క్రీన్‌షాట్, PDF లేదా వాయిస్ నోట్.\n\n"
           "హెచ్చరిక అందుకోవాల్సిన కుటుంబ సభ్యుడిని చేర్చడానికి ఇలా పంపండి:\nGUARDIAN Ravi +919876543210 ravi@example.com"),
    "hi": ("आप सुरक्षित हैं। 🛡️ जो भी संदिग्ध लगे, मुझे फ़ॉरवर्ड करें: मैसेज, लिंक, स्क्रीनशॉट, PDF या वॉइस नोट।\n\n"
           "अलर्ट पाने वाले परिवार के सदस्य को जोड़ने के लिए भेजें:\nGUARDIAN Ravi +919876543210 ravi@example.com"),
}
GUARDIAN_ACK_TO_PARENT = {
    "calling": {
        "en": "{g} has seen the alert and is calling you now. Please answer, and don't pay or share any OTP until you've spoken.",
        "te": "{g} హెచ్చరిక చూశారు, ఇప్పుడు మీకు కాల్ చేస్తున్నారు. దయచేసి ఫోన్ ఎత్తండి. మాట్లాడే వరకు ఎవరికీ డబ్బు పంపవద్దు, OTP చెప్పవద్దు.",
        "hi": "{g} ने अलर्ट देखा है और अभी आपको कॉल कर रहे हैं। कृपया फ़ोन उठाएँ। बात होने तक किसी को पैसे न भेजें, OTP न बताएँ।",
    },
    "reached": {
        "en": "{g} confirmed they've reached you. Kavach has closed this alert. Stay safe. 🙏",
        "te": "{g} మీతో మాట్లాడినట్లు నిర్ధారించారు. కవచ్ ఈ హెచ్చరికను మూసివేసింది. జాగ్రత్తగా ఉండండి. 🙏",
        "hi": "{g} ने पुष्टि की कि आपसे बात हो गई है। कवच ने यह अलर्ट बंद कर दिया है। सुरक्षित रहें। 🙏",
    },
}
TRANSCRIBE_LANG = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}
AUDIO_FORMATS = {"ogg": "ogg", "opus": "ogg", "mpeg": "mp3", "mp3": "mp3", "amr": "amr", "mp4": "mp4",
                 "m4a": "m4a", "aac": "m4a", "wav": "wav", "webm": "webm", "flac": "flac"}


# =========================================================================== entry point

def handler(event, _context):
    for record in event.get("Records", []):
        try:
            envelope = json.loads(record["Sns"]["Message"])
            entry = envelope.get("whatsAppWebhookEntry")
            entry = json.loads(entry) if isinstance(entry, str) else (entry or {})
        except (KeyError, json.JSONDecodeError) as exc:
            print(f"Skipping malformed record: {exc}")
            continue

        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for message in value.get("messages", []) or []:
                try:
                    process_message(message, names.get(message.get("from")))
                except Exception as exc:  # never let one message break the batch
                    print(f"ERROR processing {message.get('id')}: {exc!r}")
                    _safe_text(message.get("from"), kc.t("error", None))
            # value["statuses"] (sent/delivered/read receipts) are ignored on purpose.
    return {"ok": True}


def process_message(message: dict, profile_name: str | None) -> None:
    message_id = message["id"]
    if not _first_time_seen(message_id):
        print(f"Duplicate delivery of {message_id}, skipping")
        return

    phone = kc.normalize_phone(message["from"])
    kc.wa_mark_read(message_id)
    user = kc.get_user(phone)
    mtype = message.get("type")

    # ---- taps on buttons (interactive replies, or quick replies on templates)
    choice = None
    if mtype == "interactive":
        inter = message.get("interactive", {})
        choice = (inter.get("button_reply") or inter.get("list_reply") or {}).get("id")
    elif mtype == "button":
        choice = message.get("button", {}).get("payload")
    if choice:
        handle_choice(phone, user, profile_name, choice)
        return

    text = (message.get("text") or {}).get("body", "").strip()

    # ---- owner-only AWS ops mode: "aws ..." typed (not forwarded) by a number in ops_owner_phones
    ops_request = kops.ops_command(text, phone, forwarded=_is_forwarded(message))
    if ops_request is not None:
        handle_ops(phone, user, ops_request, message_id)
        return

    # ---- onboarding
    if not user:
        kc.put_user({"phone": phone, "name": profile_name or "", "status": "new", "language": "en",
                     "guardians": [], "created_at": kc.now_iso()})
        kc.wa_buttons(phone, "🛡️ Welcome to Kavach. Choose your language / భాష ఎంచుకోండి / भाषा चुनें",
                      LANG_BUTTONS)
        return
    if text and handle_command(phone, user, text):
        return
    if user.get("status") != "active":
        lang = user.get("language", "en")
        kc.wa_buttons(phone, CONSENT_TEXT.get(lang, CONSENT_TEXT["en"]), CONSENT_BUTTONS.get(lang, CONSENT_BUTTONS["en"]))
        return

    # ---- a real check
    lang = user.get("language", "en")
    kc.wa_text(phone, kc.t("checking", lang))

    media, voice_text = [], None
    if mtype in ("image", "document", "audio", "video", "sticker"):
        item = fetch_media(phone, message)
        if item:
            if mtype == "audio":
                voice_text = transcribe(item, lang)
                item["transcript"] = voice_text
            media.append(item)

    prompt = build_prompt(message, text, voice_text, media)
    result = call_agent(user, prompt, media, message_id)
    reply = (result or {}).get("reply") or kc.t("error", lang)
    kc.wa_text(phone, reply)
    send_buttons(phone, result)


def handle_ops(phone: str, user: dict | None, request: str, message_id: str) -> None:
    """Owner-only AWS console. Reads run in the ops agent; start/stop/reboot wait for a Yes tap."""
    kc.wa_text(phone, "⚙️ On it…")
    owner = user or {"phone": phone, "name": "", "language": "en", "guardians": []}
    try:
        result = call_agent(owner, request, [], message_id, mode="ops")
    except Exception as exc:
        print(f"Ops agent call failed: {exc!r}")
        result = None
    kc.wa_text(phone, (result or {}).get("reply") or "Sorry, that didn't work. Nothing was changed.")
    send_buttons(phone, result)


def send_buttons(phone: str, result: dict | None) -> None:
    """Interactive follow-ups the agent asked for: a list (appointment times), a member business's actions,
    or an ops Yes / Cancel."""
    lst = (result or {}).get("list")
    if lst:
        try:
            kc.wa_list(phone, lst["body"], lst["button"], lst["sections"], header=lst.get("header"))
        except Exception as exc:
            print(f"List not sent: {exc!r}")
    buttons = (result or {}).get("buttons") or []
    if not buttons:
        return
    try:
        kc.wa_buttons(phone, result.get("buttons_text") or "What would you like to do?",
                      [(b["id"], b["title"]) for b in buttons])
    except Exception as exc:  # the reply already went out; buttons are a bonus
        print(f"Buttons not sent: {exc!r}")


# =========================================================================== onboarding & buttons

def handle_choice(phone: str, user: dict | None, profile_name: str | None, choice: str) -> None:
    kind, _, rest = choice.partition("|")

    if kind == "LANG":
        user = user or {"phone": phone, "name": profile_name or "", "guardians": [], "created_at": kc.now_iso()}
        user["language"] = rest if rest in ("te", "hi", "en") else "en"
        user["status"] = "pending_consent"
        kc.put_user(user)
        lang = user["language"]
        kc.wa_buttons(phone, CONSENT_TEXT[lang], CONSENT_BUTTONS[lang])
        return

    if kind == "CONSENT" and user:
        lang = user.get("language", "en")
        if rest == "yes":
            user.update(status="active", consent_at=kc.now_iso())
            kc.put_user(user)
            kc.wa_text(phone, WELCOME[lang])
        else:
            user.update(status="declined")
            kc.put_user(user)
            kc.wa_text(phone, "OK. Kavach will not check your messages. Send HI any time to start again.")
        return

    if kind == "ACK":
        # Payload set in alert_family: ACK|<incident_id>|calling or ACK|<incident_id>|reached
        incident_id, _, action = rest.partition("|")
        handle_guardian_ack(phone, incident_id, action or "calling")
        return

    if kind == "GH":
        # Golden-hour check-in: GH|<incident_id>|called / GH|<incident_id>|help
        incident_id, _, action = rest.partition("|")
        incident = kc.get_incident(incident_id)
        if not incident:
            return
        lang = (user or {}).get("language", "en")
        if action == "called":
            kc.update_incident(incident_id, golden_hour_status="reported_1930")
            kc.append_incident_event(incident_id, "Victim confirmed they called 1930")
            kc.wa_text(phone, {
                "en": "Well done. Keep the complaint number safe. Next, file the written complaint at cybercrime.gov.in (the text I sent you is ready to paste) and visit your bank branch with your ID.",
                "te": "చాలా మంచిది. ఫిర్యాదు నంబర్‌ను భద్రంగా ఉంచుకోండి. తర్వాత cybercrime.gov.inలో రాతపూర్వక ఫిర్యాదు చేయండి (నేను పంపిన టెక్స్ట్‌ను పేస్ట్ చేయవచ్చు). మీ ID తో బ్యాంక్ బ్రాంచ్‌కి వెళ్ళండి.",
                "hi": "बहुत अच्छा। शिकायत नंबर संभाल कर रखें। अब cybercrime.gov.in पर लिखित शिकायत दर्ज करें (मेरा भेजा टेक्स्ट पेस्ट कर सकते हैं) और अपनी ID लेकर बैंक शाखा जाएँ।",
            }.get(lang, ""))
        else:
            kc.append_incident_event(incident_id, "Victim asked for help with 1930")
            kc.wa_text(phone, {
                "en": "Call 1930 now and say: \"I am a victim of online financial fraud and want to block a transaction.\" Keep the transaction ID ready. I've also told your family.",
                "te": "ఇప్పుడే 1930కు కాల్ చేసి ఇలా చెప్పండి: \"నేను ఆన్‌లైన్ ఆర్థిక మోసానికి గురయ్యాను, లావాదేవీని బ్లాక్ చేయాలి.\" ట్రాన్సాక్షన్ ID దగ్గర ఉంచుకోండి. మీ కుటుంబానికి కూడా తెలియజేశాను.",
                "hi": "अभी 1930 पर कॉल करें और कहें: \"मैं ऑनलाइन वित्तीय धोखाधड़ी का शिकार हूँ और ट्रांज़ैक्शन ब्लॉक करवाना है।\" ट्रांज़ैक्शन ID तैयार रखें। मैंने आपके परिवार को भी बता दिया है।",
            }.get(lang, ""))
            if user:
                kc.alert_guardians(user, incident_id, "needs help reporting a payment fraud to 1930 right now")
        return

    if kind == "OPS":
        # Owner's answer to "Stop dev-server?": OPS|yes|<token> or OPS|no|<token>. Runs here, not in the model.
        answer, _, token = rest.partition("|")
        _safe_text(phone, kops.handle_tap(phone, answer, token))
        return

    if kind in ("SLOT", "APPT") and user and user.get("status") == "active":
        # Appointment time picked (SLOT|<clinic>|<slot>) or reminder answered (APPT|going|cancel|...).
        # Plain code: the slot is booked with a conditional write, by the sender's own number.
        kclinic.handle_tap(user, choice)
        return

    if kind == "BIZ" and user and user.get("status") == "active":
        # Member-business action: BIZ|<business_id>|<action_id>|<incident_id or ->. Plain code, no model call;
        # records are looked up by the sender's own number, never by the payload.
        business_id, _, tail = rest.partition("|")
        action_id, _, incident_id = tail.partition("|")
        kb.perform_action(user, business_id, action_id, incident_id or None)
        return

    print(f"Unknown choice {choice!r} from {phone}")


def handle_guardian_ack(guardian_phone: str, incident_id: str, action: str) -> None:
    incident = kc.get_incident(incident_id)
    if not incident:
        _safe_text(guardian_phone, "This alert has expired.")
        return
    parent = kc.get_user(incident["phone"]) or {}
    guardian_name = next((g.get("name") for g in parent.get("guardians", [])
                          if kc.normalize_phone(g.get("phone", "")) == kc.normalize_phone(guardian_phone)), "Your family")
    status = "acknowledged" if action == "calling" else "resolved"
    kc.update_incident(incident_id, family_status=status, acknowledged_by=guardian_name)
    kc.append_incident_event(incident_id, f"{guardian_name} tapped '{action}'")

    lang = parent.get("language", "en")
    template = GUARDIAN_ACK_TO_PARENT["reached" if action == "reached" else "calling"]
    _safe_text(incident["phone"], template.get(lang, template["en"]).format(g=guardian_name))
    if action == "reached":
        _safe_text(guardian_phone, "Thank you. Kavach has closed the alert. 🙏")
    else:
        _safe_text(guardian_phone, f"Thanks {guardian_name}. Kavach told them you're calling. Tap \"I've reached them\" when you have spoken.")


def handle_command(phone: str, user: dict, text: str) -> bool:
    """Tiny text commands for setup. Returns True if the text was a command."""
    upper = text.upper()
    lang = user.get("language", "en")

    if upper in ("HI", "HELLO", "START", "నమస్తే", "नमस्ते") and user.get("status") in ("new", "declined"):
        kc.wa_buttons(phone, "🛡️ Welcome to Kavach. Choose your language / భాష ఎంచుకోండి / भाषा चुनें", LANG_BUTTONS)
        return True
    if upper == "STOP":
        user["status"] = "stopped"
        kc.put_user(user)
        kc.wa_text(phone, "Kavach has stopped. Send HI to start again.")
        return True
    if upper.startswith("GUARDIAN "):
        # GUARDIAN <name> <phone, spaces allowed> [email]
        body = text[len("GUARDIAN"):].strip()
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", body)
        email = email_match.group(0) if email_match else ""
        rest = body.replace(email, " ") if email else body
        phone_match = re.search(r"\+?\d[\d\s-]{8,}\d", rest)
        if not phone_match or len(re.sub(r"\D", "", phone_match.group(0))) < 10:
            kc.wa_text(phone, "Please send it like this:\nGUARDIAN Ravi +919876543210 ravi@example.com")
            return True
        name = (rest[:phone_match.start()] + " " + rest[phone_match.end():]).strip()
        guardian = {"name": re.sub(r"\s+", " ", name) or "Family", "phone": kc.normalize_phone(phone_match.group(0)),
                    "email": email.lower()}
        others = [g for g in user.get("guardians", []) if kc.normalize_phone(g.get("phone", "")) != guardian["phone"]]
        user["guardians"] = others + [guardian]
        kc.put_user(user)
        kc.wa_text(phone, f"✅ {guardian['name']} ({guardian['phone']}) will be alerted if something looks dangerous.")
        return True
    if upper.startswith("DISTRICT "):
        user["district"] = text.split(maxsplit=1)[1].strip().title()
        kc.put_user(user)
        kc.wa_text(phone, f"✅ District saved: {user['district']}. You'll get warnings about scam waves near you.")
        return True
    if upper.startswith("BANK "):
        user["bank"] = text.split(maxsplit=1)[1].strip()
        kc.put_user(user)
        kc.wa_text(phone, f"✅ Bank saved: {user['bank']}.")
        return True
    if upper.startswith("LANGUAGE"):
        kc.wa_buttons(phone, "Choose your language / భాష ఎంచుకోండి / भाषा चुनें", LANG_BUTTONS)
        return True
    return False


# =========================================================================== media & voice

def fetch_media(phone: str, message: dict) -> dict | None:
    """Download WhatsApp media into S3. Returns {s3_uri, mime_type, kind, caption, filename}."""
    mtype = message["type"]
    meta = message.get(mtype, {})
    media_id = meta.get("id")
    if not media_id:
        return None
    c = kc.cfg()
    bucket = c["media_bucket"]
    prefix = f"media/{kc.phone_digits(phone)}/{re.sub(r'[^A-Za-z0-9]', '', message['id'])[-24:]}/"
    try:
        kc.client("socialmessaging").get_whatsapp_message_media(
            mediaId=media_id,
            originationPhoneNumberId=c["whatsapp_phone_number_id"],
            destinationS3File={"bucketName": bucket, "key": prefix},
        )
    except ClientError as exc:
        print(f"Media download failed: {exc}")
        return None

    # The service appends the media id (and an extension) to the prefix, so look it up.
    s3 = kc.client("s3")
    key = kc.wait_until(lambda: next((o["Key"] for o in s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])), None),
                        timeout_s=15, every_s=1)
    if not key:
        print(f"Media not found under s3://{bucket}/{prefix}")
        return None
    return {
        "s3_uri": f"s3://{bucket}/{key}",
        "mime_type": meta.get("mime_type", ""),
        "kind": mtype,
        "caption": meta.get("caption", ""),
        "filename": meta.get("filename", ""),
    }


def transcribe(item: dict, lang: str) -> str:
    """Batch-transcribe a voice note (WhatsApp sends Ogg/Opus, which Transcribe accepts)."""
    bucket, key = item["s3_uri"][5:].split("/", 1)
    mime = (item.get("mime_type") or "audio/ogg").lower()
    fmt = next((v for k, v in AUDIO_FORMATS.items() if k in mime), "ogg")
    job = re.sub(r"[^0-9A-Za-z._-]", "", f"kavach-{int(time.time())}-{key.split('/')[-1]}")[:190]
    out_key = f"transcripts/{job}.json"
    tr = kc.client("transcribe")
    tr.start_transcription_job(
        TranscriptionJobName=job,
        Media={"MediaFileUri": f"s3://{bucket}/{key}"},
        MediaFormat=fmt,
        LanguageCode=TRANSCRIBE_LANG.get(lang, "en-IN"),
        OutputBucketName=bucket,
        OutputKey=out_key,
    )

    def done():
        status = tr.get_transcription_job(TranscriptionJobName=job)["TranscriptionJob"]["TranscriptionJobStatus"]
        return status if status in ("COMPLETED", "FAILED") else None

    status = kc.wait_until(done, timeout_s=120, every_s=2)
    if status != "COMPLETED":
        print(f"Transcription {job} ended with {status}")
        return ""
    body = kc.client("s3").get_object(Bucket=bucket, Key=out_key)["Body"].read()
    transcripts = json.loads(body).get("results", {}).get("transcripts", [])
    return " ".join(t.get("transcript", "") for t in transcripts).strip()


# =========================================================================== agent call

def build_prompt(message: dict, text: str, voice_text: str | None, media: list[dict]) -> str:
    parts = []
    ctx = message.get("context") or {}
    if ctx.get("forwarded") or ctx.get("frequently_forwarded"):
        parts.append("(The user FORWARDED this message from someone else.)")
    if text:
        parts.append(f"User's message:\n{text}")
    if voice_text is not None:
        parts.append(f"User sent a VOICE NOTE. Transcript:\n{voice_text or '[could not transcribe]'}")
    for m in media:
        if m["kind"] != "audio":
            label = m["kind"] + (f" '{m['filename']}'" if m.get("filename") else "")
            parts.append(f"User sent an {label} ({m['mime_type']}) stored at {m['s3_uri']}."
                         + (f" Caption: {m['caption']}" if m.get("caption") else ""))
    if message.get("type") == "location":
        loc = message.get("location", {})
        parts.append(f"User shared a location: {loc.get('name', '')} {loc.get('address', '')}")
    if not parts:
        parts.append(f"User sent a {message.get('type')} message with no text.")
    return "\n\n".join(parts)


def call_agent(user: dict, prompt: str, media: list[dict], message_id: str, mode: str | None = None) -> dict | None:
    digits = kc.phone_digits(user["phone"])
    kind = "kavach-ops-session" if mode == "ops" else "kavach-session"
    session_id = f"{kind}-{digits}-{datetime.now(kc.IST).strftime('%Y%m%d')}"  # >= 33 chars
    payload = {
        "prompt": prompt,
        "channel": "whatsapp",
        "message_id": message_id,
        "media": media,
        "user": {k: user.get(k) for k in ("phone", "name", "language", "district", "bank", "guardians", "email")},
    }
    if mode:
        payload["mode"] = mode
    started = time.time()
    response = AGENTCORE.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        runtimeSessionId=session_id,
        payload=json.dumps(payload).encode("utf-8"),
    )
    body = response.get("response")
    raw = body.read() if hasattr(body, "read") else b"".join(body or [])
    print(f"Agent answered in {time.time() - started:.1f}s")
    text = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"reply": str(data)}
    except json.JSONDecodeError:
        return {"reply": text}


# =========================================================================== helpers

def _is_forwarded(message: dict) -> bool:
    ctx = message.get("context") or {}
    return bool(ctx.get("forwarded") or ctx.get("frequently_forwarded"))


def _first_time_seen(message_id: str) -> bool:
    try:
        kc.table("dedupe_table").put_item(
            Item={"message_id": message_id, "expires_at": int(time.time()) + 2 * 24 * 3600},
            ConditionExpression="attribute_not_exists(message_id)",
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _safe_text(to: str | None, body: str) -> None:
    if not to or not body:
        return
    try:
        kc.wa_text(to, body)
    except Exception as exc:
        print(f"Could not send to {to}: {exc!r}")
