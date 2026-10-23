"""Sunday family digest by email (EventBridge Scheduler, 9:00 AM IST).

Invoke manually with {"phone": "+91..."} to send one family's digest during the demo.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Attr

import kavach_common as kc

VERDICT_LABEL = {"SCAM": "Scam", "LIKELY_SCAM": "Likely scam", "SUSPICIOUS": "Suspicious",
                 "LIKELY_SAFE": "Looked genuine", "NEED_MORE_INFO": "Needed more info"}


def handler(event, _context):
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    if event and event.get("phone"):
        users = [u for u in [kc.get_user(event["phone"])] if u]
    else:
        users = kc.scan_all("users_table", Attr("status").eq("active"))

    sent = 0
    for user in users:
        emails = [g["email"] for g in user.get("guardians", []) if g.get("email")]
        if user.get("email"):
            emails.append(user["email"])
        if not emails:
            continue
        incidents = kc.scan_all("incidents_table", Attr("phone").eq(user["phone"]) & Attr("created_at").gte(since))
        kc.email_send(emails, f"Kavach weekly: {summary_line(user, incidents)}", build_html(user, incidents))
        sent += 1
    return {"families_emailed": sent}


def summary_line(user: dict, incidents: list[dict]) -> str:
    blocked = sum(1 for i in incidents if i.get("verdict") in ("SCAM", "LIKELY_SCAM"))
    name = user.get("name") or "your family"
    if not incidents:
        return f"a quiet week for {name}"
    return f"{blocked} scam{'s' if blocked != 1 else ''} stopped for {name} this week"


def build_html(user: dict, incidents: list[dict]) -> str:
    name = html.escape(user.get("name") or "your family member")
    checks = len(incidents)
    scams = sum(1 for i in incidents if i.get("verdict") in ("SCAM", "LIKELY_SCAM"))
    alerts = sum(1 for i in incidents if i.get("type") in ("family_alert", "golden_hour"))
    rows = "".join(
        "<tr>"
        f"<td style='padding:8px;border-bottom:1px solid #e7e5e4'>{html.escape(i.get('created_at', '')[:10])}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #e7e5e4'>{html.escape(VERDICT_LABEL.get(i.get('verdict', ''), i.get('verdict', '-') or '-'))}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #e7e5e4'>{html.escape(i.get('check_summary') or i.get('summary') or '')}</td>"
        "</tr>"
        for i in sorted(incidents, key=lambda x: x.get("created_at", ""), reverse=True)
    )
    table = (f"<table width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;font-size:14px'>"
             f"<tr style='text-align:left;color:#78716c'><th style='padding:8px'>Date</th><th style='padding:8px'>Result</th>"
             f"<th style='padding:8px'>What was checked</th></tr>{rows}</table>") if incidents else \
        "<p>No suspicious messages were forwarded this week.</p>"
    return kc.email_shell(
        f"This week for {name}",
        f"<p style='font-size:16px'><strong>{checks}</strong> messages checked &middot; "
        f"<strong>{scams}</strong> scams stopped &middot; <strong>{alerts}</strong> family alerts</p>{table}"
        "<p style='margin-top:16px'>Tip for this week: no police officer can arrest anyone on a video call. "
        "If someone claims that, hang up and call family.</p>",
    )
