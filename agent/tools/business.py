"""Tools for Kavach member businesses: read the user's own record, and do one official action."""
from __future__ import annotations

import json

from strands import tool

import kavach_business as kb
from kavach_context import current


@tool
def check_business_records(business_name: str) -> str:
    """Look up the user's OWN record at a Kavach member business (bank, insurer, pharmacy, home services):
    account or policy status, what is due and when, orders, bookings. Also returns the business's official
    websites and its published rules (what it never does, how customers pay).

    Use when the user asks about their account, policy, order or booking at a member business, or when a
    message mentions a member business that the evidence sheet did not pick up.

    Args:
        business_name: e.g. "Nidhira Health Insurance", "Kalpavi", "Dawaghar", "Chamak".
    """
    business_id = kb.find(business_name)
    if not business_id:
        return json.dumps({"error": f"'{business_name}' is not a Kavach member business.",
                           "members": kb.member_names()})
    req = current()
    try:
        record, available = kb.get_record(business_id, req.phone), True
    except Exception:
        record, available = None, False
    check = kb.verify(business_id, record, "", {}, records_available=available)
    out = kb.for_model(check)
    out["available_actions"] = kb.action_kinds(business_id)
    return json.dumps(out, ensure_ascii=False)


@tool
def business_action(business_name: str, action: str) -> str:
    """Do ONE official action for the user with a Kavach member business. Use ONLY when the user clearly asks
    Kavach to do it (for example "send me my real policy", "ask the bank to call me", "report this to them").
    Kavach sends the confirmation to the user on WhatsApp itself; afterwards just tell them it is done.

    Args:
        business_name: e.g. "Nidhira Health Insurance", "Kalpavi Bank", "Dawaghar", "Chamak".
        action: One of:
            "summary"  - send the user their real account / policy / order details from the business's records
            "callback" - ask the business to call the user back from its official number
            "report"   - report the scam message to the business's fraud team
            "refill"   - pharmacy only: reserve the next refill, paid on delivery
            "booking"  - home services only: show the booking and the visit code the professional will say
    """
    business_id = kb.find(business_name)
    if not business_id:
        return json.dumps({"error": f"'{business_name}' is not a Kavach member business.",
                           "members": kb.member_names()})
    req = current()
    result = kb.perform_action(req.user, business_id, action.strip().lower(), req.incident_id)
    if result.get("done"):
        req.actions.append(f"business_{result['action']}")
    return json.dumps(result, ensure_ascii=False)
