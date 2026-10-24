"""Settings, opened by the agent when the person asks in their own words ("I want my daughter to get the
alerts", "Telugu lo matladu", "stop checking my messages").

The agent never changes a setting by itself: it shows the menu, or a Yes / No button, and the change happens
only when the person taps (handled in plain code by kavach_settings.handle_tap in the inbound Lambda).
"""
from __future__ import annotations

import json

from strands import tool

import kavach_common as kc
import kavach_settings as ks
from kavach_context import current

SECTIONS = ("menu", "language", "family", "linked", "pause")


@tool
def open_settings(section: str = "menu") -> str:
    """Show the person a Kavach settings menu to tap. Use when THEY ask to change their language, see or change
    family contacts (guardians), see which banks/insurers/clinics are linked to Kavach, pause or stop Kavach, or
    see their settings. Never for forwarded messages.

    Args:
        section: "menu" (everything), "language", "family" (see, add or remove family contacts), "linked"
            (member services that share records with Kavach, and unlinking), or "pause".
    """
    req = current()
    section = section if section in SECTIONS else "menu"
    user = req.user
    if section == "pause":
        req.buttons_text, req.buttons = ks.pause_buttons(user)
    elif section == "language":
        req.list_message = ks.language_list()
    elif section == "family":
        req.list_message = ks.family_list(user)
    elif section == "linked":
        req.list_message = ks.linked_list(user)
        if not req.list_message:
            return json.dumps({"shown": False, "note": ks._t("no_linked", req.language)}, ensure_ascii=False)
    else:
        req.list_message = ks.menu_list(user)
    req.actions.append(f"errand_settings_{section}")
    return json.dumps({"shown": True, "section": section,
                       "note": "Kavach sends this menu right after your reply. Nothing changes until they tap. "
                               "Reply in one or two short sentences; don't describe the menu or mention buttons."})


@tool
def add_family_contact(name: str, phone: str, email: str = "") -> str:
    """Offer to add a family member who should be alerted when the person is in danger. Use ONLY when the person
    themselves asks to add someone and gives a phone number (not for numbers inside a forwarded message).
    Kavach then asks them to tap "Yes, add"; nothing is saved until they tap.

    Args:
        name: The family member's name, e.g. "Priya".
        phone: Their mobile number, e.g. "+91 98765 43210" or "9876543210".
        email: Optional email address for alert emails.
    """
    req = current()
    digits = kc.phone_digits(phone)
    if not 10 <= len(digits) <= 15:
        return json.dumps({"added": False, "error": "That doesn't look like a full mobile number. Ask for it again."})
    if kc.normalize_phone(phone) == req.phone:
        return json.dumps({"added": False, "error": "That is the person's own number. Ask for the family member's."})
    pending = ks.remember_pending_guardian(req.phone, {"name": name, "phone": phone, "email": email})
    req.buttons_text, req.buttons = ks.confirm_add_buttons(req.user, pending)
    req.actions.append("errand_settings_add_family")
    return json.dumps({"added": False, "waiting_for_tap": True, "name": pending["name"],
                       "phone": ks.pretty_phone(pending["phone"]),
                       "note": "Kavach now asks them to confirm with a button. Say it will be added when they "
                               "confirm; don't say it is already added, and don't mention buttons."},
                      ensure_ascii=False)


SETTINGS_TOOLS = [open_settings, add_family_contact]
