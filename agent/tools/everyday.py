"""Everyday help, done safely: find a product on official stores, book a doctor at a member clinic,
order food on Swiggy.

Nothing here spends money or books anything on the model's word alone: product links only point to official
stores, an appointment is booked only when the person taps a time, and a Swiggy order is placed only when they
tap "Place order".
"""
from __future__ import annotations

import json
from datetime import datetime

from strands import tool

import food
import kavach_business as kb
import kavach_clinic as kclinic
import kavach_common as kc
import kavach_swiggy as ksw
import shopping
from kavach_context import current
from kavach_memory import get_session_manager


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
    clinics = kclinic.clinic_ids()
    if not clinics:
        return json.dumps({"error": "No member clinic is set up."})
    business_id = kb.find(clinic) if clinic else None
    business_id = business_id if business_id in clinics else clinics[0]
    p = kb.PROFILES[business_id]
    req = current()
    doctors = kclinic.match_doctors(business_id, concern)
    try:
        slots = kclinic.free_slots(business_id, doctors)
    except Exception as exc:
        return json.dumps({"error": f"Could not read the clinic's diary ({type(exc).__name__})."})
    if slots:
        req.list_message = kclinic.slot_list(business_id, slots, req.language)
    req.actions.append("errand_appointment")
    return json.dumps({
        "clinic": p["name"], "address": p.get("address", ""),
        "doctors": [{"name": d["name"], "specialty": d["specialty"], "fee_inr": d["fee"]} for d in doctors],
        "free_times": [f"{s['when']}: {s['doctor']}" for s in slots[:6]],
        "how_it_works": ("Kavach sends a list of these times right after your reply. The appointment is booked only "
                         "when the person taps a time; do not say it is booked." if slots else
                         "No free times in the next 3 days; suggest the clinic's 'Call me back' option."),
        "fee_rule": p["how_you_pay"],
    }, ensure_ascii=False)


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


@tool
def order_food(request: str) -> str:
    """Order food delivery on Swiggy for the person, from their own Swiggy account: finds restaurants and dishes,
    builds the cart, then asks them to tap "Place order" (cash on delivery). Also answers "where is my food?".
    Kavach sends the food helper's reply to them as it is.

    Args:
        request: What they want, in their own words, e.g. "2 idli and a filter coffee from a nearby tiffin centre".
    """
    req = current()
    req.actions.append("errand_food")
    if not ksw.enabled():
        return json.dumps({"available": False, "note": "Swiggy ordering isn't switched on in Kavach yet (it is waiting "
                                                       "for Swiggy's approval). Suggest the Swiggy app for now."})
    try:
        token = ksw.access_token(req.phone)
    except ksw.NotLinked as exc:
        return json.dumps({"linked": False, "note": f"{exc} Ask them to send LINK SWIGGY to connect their account."})

    def on_confirm(address_id: str, total, summary: str) -> dict:
        req.food_pending = ksw.create_pending(req.phone, address_id, total, summary)
        return req.food_pending

    digits = kc.phone_digits(req.phone)
    session = get_session_manager(f"kavach-food-session-{digits}-{datetime.now(kc.IST):%Y%m%d}", f"food-{digits}")
    try:
        result = food.run_turn(food.client_for(token), request, req.language, on_confirm, session)
    except Exception as exc:
        return json.dumps({"error": f"Swiggy could not be reached ({type(exc).__name__}). Suggest the Swiggy app."})
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    req.direct_reply = result["reply"]
    return json.dumps({"food_helper_reply": result["reply"], "confirmation_shown": bool(result["pending"]),
                       "note": "Kavach sends the food helper's reply to them as it is; keep your own reply short."},
                      ensure_ascii=False)


EVERYDAY_TOOLS = [find_product_online, find_appointment_slots, my_appointments, cancel_appointment, order_food]
