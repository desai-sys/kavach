"""Everyday help, done safely: find a product on official stores, book a doctor at a member clinic.

Nothing here spends money or books anything on the model's word alone: product links only point to official
stores, and an appointment is booked only when the person taps a time in the list Kavach sends.
"""
from __future__ import annotations

import json

from strands import tool

import kavach_business as kb
import kavach_clinic as kclinic
import shopping
from kavach_context import current


@tool
def find_product_online(product_description: str) -> str:
    """Find a product on the official Amazon India and Flipkart sites, for a person who wants to buy something
    or who saw it in an ad or photo. Returns official search links to send them. Kavach cannot place
    Amazon or Flipkart orders; the person buys in the official app.

    Args:
        product_description: Brand, product and model in English, e.g. "Prestige 5 litre pressure cooker".
    """
    links = shopping.store_links(product_description)
    current().actions.append("errand_shopping")
    return json.dumps({"product": product_description, "official_store_links": links,
                       "note": "Send these links. Tell them to buy only in the official Amazon or Flipkart app, "
                               "and never to pay a seller by UPI from an ad or a WhatsApp message."})


@tool
def find_appointment_slots(concern: str, clinic: str = "") -> str:
    """Find free appointment times with the right doctor at a Kavach member clinic. Kavach then sends the person
    a list of times to tap; the appointment is booked ONLY when they tap one.

    Args:
        concern: The health problem or doctor needed, in English, e.g. "knee pain", "fever", "eye check-up".
        clinic: Optional clinic name. Default: the member clinic.
    """
    return json.dumps(offer_slots(concern, clinic), ensure_ascii=False)


def offer_slots(concern: str, clinic: str = "") -> dict:
    """Find the doctor and free times, and queue the WhatsApp list (or a Call me back button if nothing is free).
    Also called by main.py when someone asks for a doctor and the model didn't look for times itself."""
    clinics = kclinic.clinic_ids()
    if not clinics:
        return {"error": "No member clinic is set up."}
    business_id = kb.find(clinic) if clinic else None
    business_id = business_id if business_id in clinics else clinics[0]
    p = kb.PROFILES[business_id]
    req = current()
    doctors = kclinic.match_doctors(business_id, concern)
    try:
        slots = kclinic.free_slots(business_id, doctors)
    except Exception as exc:
        return {"error": f"Could not read the clinic's diary ({type(exc).__name__})."}
    if slots:
        req.list_message = kclinic.slot_list(business_id, slots, req.language)
    else:  # nothing free: offer the clinic's call-back, so "tap Call me back" has a real button
        req.buttons = [b for b in kb.buttons_for(business_id, None, req.language) if "|callback|" in b["id"]]
        req.buttons_text = kb.buttons_text(business_id, req.language)
    if "errand_appointment" not in req.actions:
        req.actions.append("errand_appointment")
    return {
        "clinic": p["name"], "address": p.get("address", ""),
        "doctors": [{"name": d["name"], "specialty": d["specialty"], "fee_inr": d["fee"]} for d in doctors],
        "free_times": [f"{s['when']}: {s['doctor']}" for s in slots[:6]],
        "how_it_works": ("Kavach sends a list of these times right after your reply. The appointment is booked only "
                         "when the person taps a time; do not say it is booked." if slots else
                         "No free times in the next 3 days. Kavach offers the clinic's call-back right after your "
                         "reply."),
        "fee_rule": p["how_you_pay"],
    }


@tool
def my_appointments() -> str:
    """The person's upcoming appointments at Kavach member clinics."""
    req = current()
    req.actions.append("errand_appointment")
    out = []
    for business_id in kclinic.clinic_ids():
        try:
            for a in kclinic.upcoming(business_id, req.phone):
                out.append({"clinic": kb.PROFILES[business_id]["name"], "when": a["when"], "doctor": a["doctor"],
                            "token": a.get("token"), "fee_inr": a.get("fee")})
        except Exception as exc:
            return json.dumps({"error": f"Could not read appointments ({type(exc).__name__})."})
    return json.dumps({"appointments": out} if out else {"appointments": [], "note": "No upcoming appointments."},
                      ensure_ascii=False)


@tool
def cancel_appointment(which: str) -> str:
    """Cancel one of the person's upcoming appointments. Use ONLY when they clearly ask to cancel.
    Kavach sends them the confirmation itself.

    Args:
        which: Words identifying it, e.g. "Saturday 10:20" or the doctor's name. Empty = their next appointment.
    """
    req = current()
    req.actions.append("errand_appointment")
    w = (which or "").lower()
    for business_id in kclinic.clinic_ids():
        for a in kclinic.upcoming(business_id, req.phone):
            if not w or any(part in a["when"].lower() or part in a["doctor"].lower()
                            for part in w.replace(",", " ").split() if len(part) > 2):
                return json.dumps(kclinic.cancel(req.user, business_id, a["slot_id"]), ensure_ascii=False)
    return json.dumps({"cancelled": False, "note": "No matching upcoming appointment."})


EVERYDAY_TOOLS = [find_product_online, find_appointment_slots, my_appointments, cancel_appointment]
