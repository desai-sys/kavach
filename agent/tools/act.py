"""Action tools: alert the family, run the golden-hour flow, record the verdict."""
from __future__ import annotations

import html
import json
import time
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Attr
from strands import tool

import kavach_common as kc
from kavach_context import current

FAMILY_ESCALATION_MINUTES = 5
GOLDEN_HOUR_CHECK_MINUTES = 15
WAVE_THRESHOLD_DEFAULT = 3


@tool
def alert_family(severity: str, what_is_happening: str, what_family_should_do: str) -> str:
    """Alert the user's guardians on WhatsApp (and email) RIGHT NOW, with buttons for them to
    confirm they are calling. If nobody confirms within 5 minutes, Kavach escalates automatically.

    Use ONLY for high or critical risk: an ongoing scam call or video call (e.g. digital arrest),
    active pressure to pay or install an app, or money/OTP already lost.

    Args:
        severity: "critical" or "high".
        what_is_happening: One short English sentence for the family, e.g.
            "is on a video call with someone claiming to be CBI and is being asked to transfer money".
            It follows the person's name, so do not start with their name.
        what_family_should_do: One or two English sentences, e.g. "Call her now and ask her to hang up."
    """
    req = current()
    user = req.user
    guardians = user.get("guardians") or []
    if not guardians:
        return json.dumps({"alerted": [], "note": "No family member on file. Tell them to send MENU and choose "
                                                  "'Add family member'."})

    incident_id = req.ensure_incident("family_alert", severity=severity, summary=what_is_happening,
                                      family_status="alerted")
    sent = kc.alert_guardians(user, incident_id, what_is_happening)
    kc.append_incident_event(incident_id, f"Family alerted ({severity}): {', '.join(sent) or 'none'}")

    emails = [g["email"] for g in guardians if g.get("email")]
    if emails:
        name = html.escape(user.get("name") or "Your family member")
        kc.email_send(
            emails,
            f"Kavach alert: {user.get('name') or 'your family member'} may be in a scam right now",
            kc.email_shell(
                f"{name} needs you now",
                f"<p style='font-size:16px'><strong>{name}</strong> {html.escape(what_is_happening)}</p>"
                f"<p><strong>What to do:</strong> {html.escape(what_family_should_do)}</p>"
                f"<p>Their number: <a href='tel:{html.escape(req.phone)}'>{html.escape(req.phone)}</a></p>"
                f"<p style='color:#78716c'>Alert {incident_id} &middot; {kc.now_ist_str()}</p>",
            ),
        )

    kc.schedule_once(f"kavach-esc-{incident_id}", FAMILY_ESCALATION_MINUTES,
                     {"kind": "family_escalation", "incident_id": incident_id, "step": 1})
    req.actions.append("family_alerted")
    return json.dumps({"alerted": sent, "emailed": emails, "incident_id": incident_id,
                       "auto_escalation_in_minutes": FAMILY_ESCALATION_MINUTES})


@tool
def start_golden_hour(amount_inr: float, transaction_id: str = "", paid_to: str = "",
                      payment_method: str = "", bank_name: str = "", paid_at: str = "",
                      what_happened: str = "") -> str:
    """Emergency flow when money, an OTP or card details have ALREADY been given to a scammer.
    Call it immediately, before anything else. It:
      1. sends the user a ready-to-use complaint text for 1930 / cybercrime.gov.in,
      2. emails a fraud report to the bank fraud desk and the family,
      3. alerts the guardians on WhatsApp,
      4. schedules a check-in in 15 minutes to confirm 1930 was called.

    Args:
        amount_inr: Amount lost in rupees (0 if only an OTP/card was shared).
        transaction_id: UTR / UPI reference / transaction ID if known.
        paid_to: UPI ID, account number or name the money went to.
        payment_method: e.g. "UPI (PhonePe)", "Net banking", "Debit card".
        bank_name: The user's bank the money left from.
        paid_at: Date and time of payment as the user said it.
        what_happened: Two or three English sentences on the scam.
    """
    req = current()
    user = req.user
    bank_name = bank_name or user.get("bank", "")
    incident_id = req.ensure_incident("golden_hour", severity="critical", summary=what_happened,
                                      amount_inr=amount_inr, transaction_id=transaction_id, paid_to=paid_to,
                                      golden_hour_status="started", started_at_epoch=int(time.time()))

    complaint = (
        "FINANCIAL CYBER FRAUD - REQUEST TO BLOCK / HOLD FUNDS\n"
        f"Victim: {user.get('name') or '-'}, mobile {req.phone}"
        + (f", district {user['district']}" if user.get("district") else "") + "\n"
        f"Amount: Rs {amount_inr:,.0f}\n"
        f"Transaction ID / UTR: {transaction_id or 'to be added'}\n"
        f"Paid to: {paid_to or 'to be added'}\n"
        f"Method: {payment_method or '-'}   Bank: {bank_name or '-'}\n"
        f"Date/time: {paid_at or kc.now_ist_str()}\n"
        f"What happened: {what_happened or '-'}\n"
        f"Kavach reference: {incident_id}"
    )
    kc.wa_text(req.phone, "📋 Keep this ready when you call 1930 or file at cybercrime.gov.in:\n\n" + complaint)

    c = kc.cfg()
    family_emails = [g["email"] for g in user.get("guardians", []) if g.get("email")]
    report_html = kc.email_shell(
        "Urgent: fraudulent transaction, please block and hold",
        "<pre style='white-space:pre-wrap;font-family:Arial,Helvetica,sans-serif;font-size:14px'>"
        + html.escape(complaint) + "</pre>"
        "<p>The customer has been told to call the National Cyber Crime Helpline 1930. "
        "Please place a hold on the beneficiary account under the CFCFRMS process.</p>",
    )
    to = [c.get("bank_fraud_email")] + family_emails
    kc.email_send(to, f"URGENT fraud report {incident_id}: Rs {amount_inr:,.0f} from {user.get('name') or req.phone}",
                  report_html, complaint, reply_to=family_emails or None)

    sent = kc.alert_guardians(user, incident_id,
                              f"has lost Rs {amount_inr:,.0f} to a suspected scam. Help them call 1930 in the next few minutes")
    kc.schedule_once(f"kavach-gh-{incident_id}", GOLDEN_HOUR_CHECK_MINUTES,
                     {"kind": "golden_hour_check", "incident_id": incident_id})
    kc.append_incident_event(incident_id, "Golden hour started: complaint text sent, bank and family emailed")
    req.actions.append("golden_hour_started")
    return json.dumps({"incident_id": incident_id, "complaint_text_sent_to_user": True,
                       "bank_emailed": bool(c.get("bank_fraud_email")), "family_alerted": sent,
                       "check_in_minutes": GOLDEN_HOUR_CHECK_MINUTES})


@tool
def record_verdict(verdict: str, scam_type: str, risk_level: str, summary: str,
                   identifiers: list[str] | None = None) -> str:
    """Record the outcome of this check. Call exactly ONCE, at the end of every investigation.

    Args:
        verdict: One of SCAM, LIKELY_SCAM, SUSPICIOUS, LIKELY_SAFE, NEED_MORE_INFO.
        scam_type: Playbook id (e.g. digital_arrest, bank_kyc) or "other" / "none".
        risk_level: critical, high, medium or low.
        summary: One English sentence describing what was checked and found.
        identifiers: Scammer phone numbers, UPI IDs, account numbers and domains found (never the user's own).
    """
    current().model_verdict = verdict.upper()
    return json.dumps(save_verdict(verdict, scam_type, risk_level, summary, identifiers, source="agent"))


def save_verdict(verdict: str, scam_type: str, risk_level: str, summary: str,
                 identifiers: list[str] | None = None, source: str = "agent") -> dict:
    """Store the verdict on the incident and add scam identifiers to the community database.

    Safe to call more than once per request: each identifier is reported at most once.
    """
    req = current()
    verdict = verdict.upper()
    req.verdict = verdict
    incident_id = req.ensure_incident("check")
    kc.update_incident(incident_id, verdict=verdict, scam_type=scam_type, risk_level=risk_level,
                       check_summary=summary, verdict_source=source)

    reported = []
    if verdict in ("SCAM", "LIKELY_SCAM"):
        from tools.investigate import _normalize_identifier  # local import avoids a cycle

        own = {req.phone} | {kc.normalize_phone(g.get("phone", "")) for g in req.user.get("guardians", [])}
        expires = int(time.time()) + 90 * 24 * 3600
        for raw in identifiers or []:
            ident = _normalize_identifier(raw)
            if not ident or ident in own or ident in req.reported:
                continue
            kc.table("reports_table").put_item(Item=kc.clean_for_dynamo({
                "identifier": ident, "report_id": kc.new_id("rep"), "scam_type": scam_type,
                "district": req.user.get("district", ""), "created_at": kc.now_iso(), "expires_at": expires,
            }))
            req.reported.add(ident)
            reported.append(ident)
        if reported:
            _maybe_trigger_wave(scam_type, req.user.get("district", ""), summary)
    return {"recorded": True, "incident_id": incident_id, "community_reports_added": reported}


def _maybe_trigger_wave(scam_type: str, district: str, summary: str) -> None:
    """If the same scam type is reported several times in one district within 24 hours, warn everyone there."""
    if not district or scam_type in ("other", "none", ""):
        return
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    recent = kc.scan_all("reports_table", Attr("scam_type").eq(scam_type) & Attr("district").eq(district)
                         & Attr("created_at").gte(since))
    reports = [r for r in recent if r.get("report_id", "").startswith("rep-")]
    threshold = int(kc.cfg().get("wave_threshold", WAVE_THRESHOLD_DEFAULT))
    if len(reports) < threshold:
        return
    kc.client("lambda").invoke(
        FunctionName=kc.cfg()["community_function_name"],
        InvocationType="Event",
        Payload=json.dumps({"district": district, "scam_type": scam_type, "summary": summary,
                            "report_count": len(reports)}).encode(),
    )
