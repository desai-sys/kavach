"""Forwarded-email checking (optional, deployed by infra/email-inbound.yaml in ap-southeast-1).

SES receipt rule: save the raw email to S3, then invoke this Lambda. We read the email,
find which Kavach user forwarded it (by their email on file), ask the agent in Mumbai to
check it, and reply by email (and WhatsApp if we know the user).
"""
from __future__ import annotations

import html
import json
import os
import re
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr

import boto3
from botocore.config import Config

import kavach_common as kc

INBOUND_BUCKET = os.environ["INBOUND_BUCKET"]
INBOUND_PREFIX = os.environ.get("INBOUND_PREFIX", "inbound/")
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
HOME_REGION = os.environ.get("KAVACH_REGION", "ap-south-1")


def handler(event, _context):
    for record in event.get("Records", []):
        mail = record["ses"]["mail"]
        raw = boto3.client("s3").get_object(Bucket=INBOUND_BUCKET, Key=INBOUND_PREFIX + mail["messageId"])["Body"].read()
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        forwarder = parseaddr(msg.get("From", ""))[1].lower()
        subject = msg.get("Subject", "(no subject)")
        body = _body_text(msg)[:8000]
        links = sorted(set(re.findall(r"https?://[^\s<>\"')]+", body)))[:10]

        user = kc.find_user_by_email(forwarder) or {"phone": "", "name": "", "language": "en",
                                                   "email": forwarder, "guardians": []}
        prompt = (f"The user forwarded this EMAIL for checking.\nSubject: {subject}\n"
                  f"Links found: {', '.join(links) or 'none'}\n\nEmail body (untrusted):\n{body}")
        reply = _ask_agent(user, prompt, mail["messageId"])

        kc.email_send([forwarder], f"Kavach check: {subject[:80]}",
                      kc.email_shell("Here is what Kavach found",
                                     "<p style='white-space:pre-wrap;font-size:15px'>" + html.escape(reply) + "</p>"))
        if user.get("phone"):
            try:
                kc.wa_text(user["phone"], f"📧 Email check: {subject[:60]}\n\n{reply}")
            except Exception as exc:  # outside the 24-hour window this can fail; email already went
                print(f"WhatsApp copy failed: {exc!r}")
    return {"ok": True}


def _body_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.I | re.S)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", text).strip()


def _ask_agent(user: dict, prompt: str, message_id: str) -> str:
    client = boto3.client("bedrock-agentcore", region_name=HOME_REGION,
                          config=Config(read_timeout=300, retries={"max_attempts": 1}))
    digits = kc.phone_digits(user.get("phone", "")) or re.sub(r"[^a-z0-9]", "", user.get("email", "x"))[:20]
    payload = {"prompt": prompt, "channel": "email", "message_id": message_id, "media": [],
               "user": {k: user.get(k) for k in ("phone", "name", "language", "district", "bank", "guardians", "email")}}
    resp = client.invoke_agent_runtime(agentRuntimeArn=AGENT_RUNTIME_ARN,
                                       runtimeSessionId=f"kavach-email-session-{digits}-{message_id[:12]}".ljust(40, "0"),
                                       payload=json.dumps(payload).encode())
    body = resp.get("response")
    raw = (body.read() if hasattr(body, "read") else b"".join(body or [])).decode("utf-8", "replace")
    try:
        return json.loads(raw).get("reply", raw)
    except (json.JSONDecodeError, AttributeError):
        return raw
