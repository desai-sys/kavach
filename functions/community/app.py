"""Scam-wave warning: tell every protected person in a district about a scam spreading there.

Invoked asynchronously by the agent's record_verdict tool when several reports of the same
scam type arrive from one district within 24 hours, or manually:
  {"district": "Kurnool", "scam_type": "electricity_disconnection",
   "summary": "Fake electricity disconnection messages asking you to call an 'officer'"}
Uses the approved WhatsApp template (business-initiated, works outside the 24-hour window).
"""
from __future__ import annotations

import time

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

import kavach_common as kc


def handler(event, _context):
    district = (event.get("district") or "").strip()
    scam_type = event.get("scam_type", "scam")
    summary = event.get("summary") or "A scam is spreading in your area"
    if not district:
        return {"sent": 0, "reason": "no district"}

    # One warning per district + scam type per 12 hours.
    marker = f"WAVE#{district.lower()}#{scam_type}"
    try:
        kc.table("reports_table").put_item(
            Item={"identifier": marker, "report_id": "wave", "created_at": kc.now_iso(),
                  "expires_at": int(time.time()) + 12 * 3600},
            ConditionExpression="attribute_not_exists(identifier) OR expires_at < :now",
            ExpressionAttributeValues={":now": int(time.time())},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return {"sent": 0, "reason": "already warned recently"}
        raise

    c = kc.cfg()
    template = c.get("scam_warning_template", "kavach_scam_warning")
    language = c.get("template_language", "en")
    people = kc.scan_all("users_table", Attr("status").eq("active") & Attr("district").eq(district))
    sent = 0
    for person in people:
        try:
            kc.wa_template(person["phone"], template, language, [district, summary])
            sent += 1
        except Exception as exc:
            # Template not approved yet: a normal message still reaches people who messaged in the last 24 hours.
            try:
                kc.wa_text(person["phone"], f"⚠️ Kavach scam warning for {district}: {summary}. "
                                            "Don't click links, share OTPs or pay anyone. Forward anything "
                                            "suspicious to Kavach.")
                sent += 1
            except Exception:
                print(f"Warning to {person['phone']} failed: {exc!r}")
    print(f"Scam-wave warning '{scam_type}' sent to {sent} people in {district}")
    return {"sent": sent}
