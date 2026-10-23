"""Shared helpers for Kavach.

This one file is used in two places:
  * the Lambda functions (packaged as a Lambda layer by SAM), and
  * the Kavach agent on AgentCore Runtime (copied in by scripts/install_agent.py).

Everything reads its settings from one SSM parameter (default /kavach/config),
which the SAM stack creates. That keeps resource names in a single place.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable

import boto3
from boto3.dynamodb.conditions import Attr

IST = timezone(timedelta(hours=5, minutes=30))
CONFIG_PARAM = os.getenv("KAVACH_CONFIG_PARAM", "/kavach/config")
DEFAULT_REGION = os.getenv("KAVACH_REGION") or os.getenv("AWS_REGION") or "ap-south-1"


# --------------------------------------------------------------------------- config

@lru_cache(maxsize=1)
def cfg() -> dict:
    """Load the Kavach config JSON from SSM Parameter Store (cached per process)."""
    ssm = boto3.client("ssm", region_name=DEFAULT_REGION)
    try:
        value = ssm.get_parameter(Name=CONFIG_PARAM)["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        try:
            account = boto3.client("sts", region_name=DEFAULT_REGION).get_caller_identity()["Account"]
        except Exception:
            account = "unknown"
        raise RuntimeError(
            f"Kavach config {CONFIG_PARAM} was not found in region {DEFAULT_REGION} of AWS account {account}. "
            "Deploy the SAM stack (template.yaml) to this region and account first, or set AWS_REGION to the "
            "region where you deployed it.") from None
    data = json.loads(value)
    data.setdefault("region", DEFAULT_REGION)
    data.setdefault("meta_api_version", "v20.0")
    return data


@lru_cache(maxsize=None)
def client(name: str, region: str | None = None):
    return boto3.client(name, region_name=region or cfg()["region"])


@lru_cache(maxsize=None)
def table(key: str):
    """key is one of: users_table, incidents_table, reports_table, dedupe_table,
    business_records_table, business_signals_table."""
    return boto3.resource("dynamodb", region_name=cfg()["region"]).Table(cfg()[key])


# --------------------------------------------------------------------------- small utils

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_ist_str() -> str:
    return datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")


def new_id(prefix: str) -> str:
    stamp = datetime.now(IST).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"


def normalize_phone(phone: str) -> str:
    """Return E.164 with a leading '+'. Bare 10-digit Indian numbers get +91."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = "91" + digits
    return "+" + digits if digits else ""


def phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def to_jsonable(obj: Any) -> Any:
    """DynamoDB returns Decimal; make things json.dumps-safe."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    return obj


def clean_for_dynamo(obj: Any) -> Any:
    """Floats are not allowed in DynamoDB; drop None and empty strings too."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: clean_for_dynamo(v) for k, v in obj.items() if v is not None and v != ""}
    if isinstance(obj, list):
        return [clean_for_dynamo(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- language strings

STRINGS = {
    "checking": {
        "te": "🔍 పరిశీలిస్తున్నాను… ఒక్క నిమిషం.",
        "hi": "🔍 जाँच कर रहा हूँ… एक मिनट।",
        "en": "🔍 Checking this for you… one minute.",
    },
    "error": {
        "te": "క్షమించండి, ఇప్పుడు దీన్ని పరిశీలించలేకపోయాను. ఎవరైనా డబ్బు కోసం ఒత్తిడి చేస్తుంటే చెల్లించవద్దు. సహాయం కోసం 1930కు కాల్ చేయండి.",
        "hi": "क्षमा करें, अभी मैं इसकी जाँच नहीं कर पाया। अगर कोई पैसे के लिए दबाव डाल रहा है तो भुगतान न करें। मदद के लिए 1930 पर कॉल करें।",
        "en": "Sorry, I couldn't check that right now. If anyone is pressuring you to pay, don't pay. Call 1930 for help.",
    },
}


def t(key: str, lang: str | None) -> str:
    options = STRINGS.get(key, {})
    return options.get(lang or "en") or options.get("en", key)


# --------------------------------------------------------------------------- WhatsApp

def wa_send(message: dict) -> dict:
    """Send any WhatsApp Cloud API message body through End User Messaging Social."""
    c = cfg()
    message.setdefault("messaging_product", "whatsapp")
    return client("socialmessaging").send_whatsapp_message(
        originationPhoneNumberId=c["whatsapp_phone_number_id"],
        message=json.dumps(message).encode("utf-8"),
        metaApiVersion=c["meta_api_version"],
    )


def wa_text(to: str, body: str) -> None:
    """Plain text, split into WhatsApp's 4,096-character limit."""
    to = normalize_phone(to)
    for chunk in _chunks(body, 4000):
        wa_send({"to": to, "type": "text", "text": {"preview_url": False, "body": chunk}})


def wa_buttons(to: str, body: str, buttons: list[tuple[str, str]], header: str | None = None) -> None:
    """Up to 3 quick-reply buttons: [(id, title<=20 chars), ...]. Only inside the 24-hour window."""
    interactive: dict = {
        "type": "button",
        "body": {"text": body[:1024]},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": bid, "title": title[:20]}} for bid, title in buttons[:3]
        ]},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    wa_send({"to": normalize_phone(to), "recipient_type": "individual", "type": "interactive", "interactive": interactive})


def wa_template(to: str, name: str, language: str, body_params: list[str],
                quick_reply_payloads: list[str] | None = None) -> dict:
    """Send an approved template (works outside the 24-hour window).

    body_params fill {{1}}, {{2}}, ... in order. quick_reply_payloads set the payload
    returned when the person taps button 0, 1, ... (so we know which incident it was).
    """
    components: list[dict] = []
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": _template_safe(p)} for p in body_params],
        })
    for index, payload in enumerate(quick_reply_payloads or []):
        components.append({
            "type": "button", "sub_type": "quick_reply", "index": str(index),
            "parameters": [{"type": "payload", "payload": payload}],
        })
    return wa_send({
        "to": normalize_phone(to), "type": "template",
        "template": {"name": name, "language": {"code": language}, "components": components},
    })


def alert_guardians(user: dict, incident_id: str, summary: str,
                    guardians: list[dict] | None = None) -> list[str]:
    """Send the approved family-alert template to each guardian.

    Template body: {{1}} = protected person's name, {{2}} = what is happening, {{3}} = their phone.
    Buttons: 0 = "I'm calling now", 1 = "I've reached them" (payloads carry the incident id).
    """
    c = cfg()
    template = c.get("family_alert_template", "kavach_family_alert")
    language = c.get("template_language", "en")
    name = user.get("name") or "Your family member"
    # v1 body reads "{{1}} {{2}}." (summary continues the name); v2 labels each field,
    # so {{2}} must be a full sentence that starts with the name.
    situation = f"{name} {summary}" if "v2" in template else summary
    sent = []
    buttons = [(f"ACK|{incident_id}|calling", "I'm calling now"), (f"ACK|{incident_id}|reached", "I've reached them")]
    for g in (guardians if guardians is not None else user.get("guardians", [])):
        if not g.get("phone"):
            continue
        try:
            wa_template(g["phone"], template, language,
                        [name, situation, user.get("phone", "")],
                        [bid for bid, _title in buttons])
            sent.append(normalize_phone(g["phone"]))
        except Exception as exc:
            # Template not approved yet (or rejected): a normal message with the same buttons still reaches a
            # guardian who has messaged Kavach in the last 24 hours.
            print(f"Family alert template to {g.get('phone')} failed ({exc!r}); trying a normal message")
            try:
                wa_buttons(g["phone"], f"🚨 Kavach alert: {name} {summary}.\nTheir number: {user.get('phone', '')}\n"
                                       "Please call them now.", buttons, header="Kavach family alert")
                sent.append(normalize_phone(g["phone"]))
            except Exception as exc2:
                print(f"Family alert to {g.get('phone')} failed: {exc2!r}")
    return sent


def wa_mark_read(message_id: str) -> None:
    try:
        wa_send({"status": "read", "message_id": message_id})
    except Exception as exc:  # read receipts are nice-to-have
        print(f"mark_read failed: {exc}")


def _template_safe(text: str) -> str:
    # Meta rejects template params with newlines, tabs or 4+ consecutive spaces.
    text = re.sub(r"[\r\n\t]+", " ", str(text))
    return re.sub(r" {4,}", "   ", text)[:900]


def _chunks(text: str, size: int) -> Iterable[str]:
    text = text or ""
    while text:
        yield text[:size]
        text = text[size:]


# --------------------------------------------------------------------------- email

def email_send(to: list[str], subject: str, html: str, text: str | None = None,
               reply_to: list[str] | None = None) -> str | None:
    recipients = [a for a in (to or []) if a]
    if not recipients:
        return None
    body: dict = {"Html": {"Data": html, "Charset": "UTF-8"}}
    if text:
        body["Text"] = {"Data": text, "Charset": "UTF-8"}
    kwargs: dict = {
        "FromEmailAddress": cfg()["from_email"],
        "Destination": {"ToAddresses": recipients},
        "Content": {"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": body}},
    }
    if reply_to:
        kwargs["ReplyToAddresses"] = reply_to
    return client("sesv2").send_email(**kwargs).get("MessageId")


def email_shell(title: str, inner_html: str) -> str:
    """Minimal, mail-client-safe HTML wrapper."""
    return f"""<!doctype html><html><body style="margin:0;padding:24px;background:#f5f5f4;font-family:Arial,Helvetica,sans-serif;color:#1c1917">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:8px">
<tr><td style="padding:20px 24px;border-bottom:3px solid #b45309"><strong style="font-size:18px">Kavach</strong>
<span style="color:#78716c"> &middot; family scam shield</span></td></tr>
<tr><td style="padding:24px"><h2 style="margin:0 0 12px;font-size:20px">{title}</h2>{inner_html}</td></tr>
<tr><td style="padding:16px 24px;color:#78716c;font-size:12px">Sent by Kavach. Never share OTPs, PINs or passwords with anyone.
For cyber fraud, call 1930 or report at cybercrime.gov.in.</td></tr></table></body></html>"""


# --------------------------------------------------------------------------- users & incidents

def get_user(phone: str) -> dict | None:
    item = table("users_table").get_item(Key={"phone": normalize_phone(phone)}).get("Item")
    return to_jsonable(item) if item else None


def put_user(user: dict) -> None:
    user = dict(user)
    user["phone"] = normalize_phone(user["phone"])
    user["updated_at"] = now_iso()
    table("users_table").put_item(Item=clean_for_dynamo(user))


def find_user_by_email(email: str) -> dict | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    for item in scan_all("users_table", Attr("email").eq(email)):
        return item
    return None


def guardian_of(phone: str) -> list[dict]:
    """Return the protected people who list this phone as a guardian."""
    phone = normalize_phone(phone)
    return [u for u in scan_all("users_table")
            if any(normalize_phone(g.get("phone", "")) == phone for g in u.get("guardians", []))]


def put_incident(incident: dict) -> dict:
    incident = dict(incident)
    incident.setdefault("incident_id", new_id("inc"))
    incident.setdefault("created_at", now_iso())
    incident["updated_at"] = now_iso()
    table("incidents_table").put_item(Item=clean_for_dynamo(incident))
    return incident


def get_incident(incident_id: str) -> dict | None:
    item = table("incidents_table").get_item(Key={"incident_id": incident_id}).get("Item")
    return to_jsonable(item) if item else None


def update_incident(incident_id: str, **fields: Any) -> None:
    fields["updated_at"] = now_iso()
    fields = clean_for_dynamo(fields)
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    table("incidents_table").update_item(
        Key={"incident_id": incident_id}, UpdateExpression=expr,
        ExpressionAttributeNames=names, ExpressionAttributeValues=values,
    )


def append_incident_event(incident_id: str, event: str) -> None:
    table("incidents_table").update_item(
        Key={"incident_id": incident_id},
        UpdateExpression="SET #ev = list_append(if_not_exists(#ev, :empty), :new), updated_at = :now",
        ExpressionAttributeNames={"#ev": "events"},
        ExpressionAttributeValues={":empty": [], ":new": [f"{now_ist_str()}: {event}"], ":now": now_iso()},
    )


def scan_all(table_key: str, filter_expression=None) -> list[dict]:
    kwargs: dict = {}
    if filter_expression is not None:
        kwargs["FilterExpression"] = filter_expression
    items: list[dict] = []
    tbl = table(table_key)
    while True:
        page = tbl.scan(**kwargs)
        items.extend(to_jsonable(i) for i in page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


# --------------------------------------------------------------------------- timers

def schedule_once(name_prefix: str, minutes_from_now: float, payload: dict) -> str:
    """Fire the escalation Lambda once, N minutes from now, via EventBridge Scheduler."""
    c = cfg()
    fire_at = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    name = re.sub(r"[^0-9A-Za-z_.-]", "-", f"{name_prefix}-{uuid.uuid4().hex[:8]}")[:64]
    client("scheduler").create_schedule(
        Name=name,
        ScheduleExpression=f"at({fire_at.strftime('%Y-%m-%dT%H:%M:%S')})",
        ScheduleExpressionTimezone="UTC",
        FlexibleTimeWindow={"Mode": "OFF"},
        ActionAfterCompletion="DELETE",
        Target={
            "Arn": c["escalation_function_arn"],
            "RoleArn": c["scheduler_role_arn"],
            "Input": json.dumps(payload),
        },
    )
    return name


def wait_until(check, timeout_s: float = 90, every_s: float = 2.0):
    """Poll check() until it returns something truthy or the timeout passes."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        result = check()
        if result:
            return result
        time.sleep(every_s)
    return None
