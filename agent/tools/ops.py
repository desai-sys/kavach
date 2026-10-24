"""Tools for the owner-only ops mode (see layers/common/kavach_ops.py for the safety design).

All of these are read-only except request_instance_action, which only REQUESTS a start / stop / reboot;
the owner must tap Yes before the inbound Lambda runs it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Attr
from strands import tool

import kavach_common as kc
import kavach_ops as kops
from kavach_context import current

KAVACH_FUNCTIONS = ["kavach-inbound", "kavach-escalation", "kavach-weekly-digest", "kavach-community-alert"]
READ_SERVICES = {"ec2", "s3", "lambda", "rds", "cloudwatch", "cloudformation", "dynamodb", "ce", "sesv2",
                 "socialmessaging", "ecs", "elbv2", "autoscaling", "sns", "sqs", "budgets"}
# Read calls that can return secrets or data (not just configuration) are refused even if IAM allowed them.
DENIED_READS = {"get_object", "get_object_torrent", "get_secret_value", "get_parameter", "get_parameters",
                "get_parameters_by_path", "get_password_data", "get_console_output", "get_console_screenshot",
                "describe_instance_attribute", "get_launch_template_data", "get_function", "get_item",
                "get_records", "get_whatsapp_message_media", "get_query_results", "get_log_events"}
MAX_CHARS = 5000


def _json(data) -> str:
    text = json.dumps(data, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "...(truncated)"


@tool
def list_instances(name_or_id: str = "", region: str = "") -> str:
    """List the owner's EC2 instances: name, id, state, type, region, IP addresses, launch time.

    Args:
        name_or_id: Optional filter: part of the instance's Name tag, or an instance id (i-...).
        region: Optional AWS region code, e.g. "ap-south-1" or "us-east-1". Default: the configured regions.
    """
    try:
        found = kops.find_instances(name_or_id, region)
    except Exception as exc:
        return _json({"error": f"{type(exc).__name__}: {exc}"[:300]})
    return _json({"regions_checked": [region] if region else kops.regions(), "instances": found,
                  "count": len(found)})


@tool
def aws_spend_this_month() -> str:
    """Month-to-date AWS cost for this account: total and the top services (from Cost Explorer)."""
    today = datetime.now(timezone.utc).date()
    start, end = today.replace(day=1), today + timedelta(days=1)
    try:
        resp = kc.client("ce", "us-east-1").get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()}, Granularity="MONTHLY",
            Metrics=["UnblendedCost"], GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}])
    except Exception as exc:
        return _json({"error": f"{type(exc).__name__}: {exc}"[:300],
                      "hint": "Cost Explorer must be enabled once in the Billing console."})
    totals: dict[str, float] = {}
    unit = ""
    for period in resp.get("ResultsByTime", []):
        for g in period.get("Groups", []):
            cost = g["Metrics"]["UnblendedCost"]
            unit = cost.get("Unit", unit)
            totals[g["Keys"][0]] = totals.get(g["Keys"][0], 0.0) + float(cost.get("Amount", 0))
    top = sorted(totals.items(), key=lambda kv: -kv[1])
    return _json({"period": f"{start} to {today}", "unit": unit, "total": round(sum(totals.values()), 2),
                  "top_services": [{"service": s, "amount": round(a, 2)} for s, a in top[:6] if a >= 0.005]})


@tool
def kavach_status() -> str:
    """Health of the Kavach deployment: WhatsApp template approval status, whether SES can email anyone
    (production access) or only verified addresses (sandbox), Lambda errors in the last 24 hours, today's scam
    checks and family alerts, and WhatsApp messages Meta failed to deliver (e.g. a template that isn't
    approved, or a normal message outside the 24-hour window)."""
    out: dict = {}
    try:
        sm = kc.client("socialmessaging")
        accounts = sm.list_linked_whatsapp_business_accounts().get("linkedAccounts", [])
        out["whatsapp_accounts"] = [{"name": a.get("wabaName"), "status": a.get("registrationStatus")} for a in accounts]
        out["whatsapp_templates"] = [
            {"name": t.get("templateName"), "language": t.get("templateLanguage"), "status": t.get("templateStatus"),
             "category": t.get("templateCategory")}
            for a in accounts for t in sm.list_whatsapp_message_templates(id=a["id"]).get("templates", [])]
    except Exception as exc:
        out["whatsapp_templates"] = f"unavailable ({type(exc).__name__})"
    try:
        acct = kc.client("sesv2").get_account()
        quota = acct.get("SendQuota", {})
        out["email"] = {"production_access": acct.get("ProductionAccessEnabled"),
                        "sending_enabled": acct.get("SendingEnabled"),
                        "max_per_24h": quota.get("Max24HourSend"), "sent_last_24h": quota.get("SentLast24Hours")}
    except Exception as exc:
        out["email"] = f"unavailable ({type(exc).__name__})"
    try:
        cw = kc.client("cloudwatch")
        now = datetime.now(timezone.utc)
        health = []
        for fn in KAVACH_FUNCTIONS:
            row = {"function": fn}
            for metric in ("Invocations", "Errors"):
                points = cw.get_metric_statistics(
                    Namespace="AWS/Lambda", MetricName=metric, Dimensions=[{"Name": "FunctionName", "Value": fn}],
                    StartTime=now - timedelta(hours=24), EndTime=now, Period=86400, Statistics=["Sum"]).get("Datapoints", [])
                row[metric.lower() + "_24h"] = int(sum(p.get("Sum", 0) for p in points))
            health.append(row)
        out["lambda_last_24h"] = health
    except Exception as exc:
        out["lambda_last_24h"] = f"unavailable ({type(exc).__name__})"
    try:
        midnight_ist = datetime.now(kc.IST).replace(hour=0, minute=0, second=0, microsecond=0)
        since = midnight_ist.astimezone(timezone.utc).isoformat(timespec="seconds")
        rows = kc.scan_all("incidents_table", Attr("created_at").gte(since))
        verdicts: dict[str, int] = {}
        for r in rows:
            v = r.get("verdict") or "no verdict"
            verdicts[v] = verdicts.get(v, 0) + 1
        out["today"] = {"checks": len(rows), "verdicts": verdicts,
                        "family_alerts": sum(1 for r in rows if r.get("family_status")),
                        "golden_hour": sum(1 for r in rows if r.get("golden_hour_status"))}
    except Exception as exc:
        out["today"] = f"unavailable ({type(exc).__name__})"
    try:  # WhatsApp messages Meta refused after accepting them (logged by the inbound Lambda)
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        failed = [u for u in kc.scan_all("users_table", Attr("last_delivery_error").exists())
                  if str((u.get("last_delivery_error") or {}).get("at", "")) >= since]
        out["whatsapp_delivery_failures_24h"] = [
            {"to": "+" + kc.phone_digits(u["phone"])[:4] + "…" + kc.phone_digits(u["phone"])[-3:],
             "at": u["last_delivery_error"].get("at"), "errors": u["last_delivery_error"].get("errors")}
            for u in failed[:10]]
    except Exception as exc:
        out["whatsapp_delivery_failures_24h"] = f"unavailable ({type(exc).__name__})"
    return _json(out)


@tool
def aws_read(service: str, operation: str, parameters: dict | None = None, region: str = "") -> str:
    """Any other READ-ONLY lookup in the owner's AWS account, as one boto3 call. Use the more specific tools
    first. Only describe_*, list_* and get_* operations on common services are allowed, and calls that
    return secrets or stored data are refused.

    Args:
        service: boto3 client name, e.g. "s3", "lambda", "rds", "cloudformation", "ecs", "dynamodb".
        operation: boto3 method name in snake_case, e.g. "list_buckets", "list_functions", "describe_db_instances".
        parameters: Optional keyword arguments for the call, e.g. {"StackName": "kavach"}.
        region: Optional AWS region code. Default: the first configured region.
    """
    service, operation = (service or "").strip().lower(), (operation or "").strip()
    if service not in READ_SERVICES:
        return _json({"error": f"'{service}' is not available in ops mode.", "allowed": sorted(READ_SERVICES)})
    if not re.fullmatch(r"(describe|list|get)_[a-z0-9_]+", operation) or operation in DENIED_READS:
        return _json({"error": f"'{operation}' is not allowed. Ops mode can only read configuration and status "
                               "(describe_*, list_*, get_*), never change anything or read secrets or data."})
    client = kc.client(service, region or kops.regions()[0])
    if not hasattr(client, operation):
        return _json({"error": f"{service} has no operation {operation}"})
    try:
        resp = getattr(client, operation)(**(parameters or {}))
    except Exception as exc:
        return _json({"error": f"{type(exc).__name__}: {exc}"[:400]})
    resp.pop("ResponseMetadata", None)
    return _json(resp)


@tool
def request_instance_action(name_or_id: str, action: str, region: str = "") -> str:
    """Ask to start, stop or reboot ONE EC2 instance. This does NOT run it: Kavach shows the owner Yes / Cancel
    buttons, and only a Yes tap runs the action. Terminating or deleting is not possible.

    Args:
        name_or_id: The instance's Name tag (or part of it) or its id (i-...).
        action: "start", "stop" or "reboot".
        region: Optional AWS region code. Default: search the configured regions.
    """
    action = (action or "").strip().lower()
    if action not in kops.ACTIONS:
        return _json({"error": f"'{action}' is not allowed. Ops mode can only start, stop or reboot instances. "
                               "Terminate, delete and security changes must be done in the AWS console."})
    req = current()
    if req.ops_pending:
        return _json({"error": "Only one action per message. Ask the owner to confirm the first one, then ask again."})
    try:
        inst, candidates = kops.pick_instance(name_or_id, region)
    except Exception as exc:
        return _json({"error": f"{type(exc).__name__}: {exc}"[:300]})
    if not inst:
        return _json({"error": "No single instance matched. Ask the owner which one they mean.",
                      "candidates": candidates[:10]})
    if inst["state"] not in kops.ALLOWED_FROM_STATE[action]:
        return _json({"error": f"{inst['name'] or inst['id']} is {inst['state']}, so it can't be {action}ed now.",
                      "instance": inst})
    req.ops_pending = kops.create_pending(req.phone, action, inst)
    req.actions.append(f"ops_requested_{action}")
    return _json({"pending_confirmation": True, "instance": inst,
                  "note": "Kavach now shows the owner Yes / Cancel buttons. Nothing changes until they tap Yes. "
                          "Tell them to tap Yes to go ahead."})


OPS_TOOLS = [list_instances, aws_spend_this_month, kavach_status, aws_read, request_instance_action]
