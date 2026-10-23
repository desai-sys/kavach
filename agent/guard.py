"""Checks applied to the model's reply before it reaches the user.

1. Verdict floor: the reply may not be milder than the fixed rules allow.
2. Grounding: the reply may not contain websites or phone numbers that Kavach never saw or verified.
If either fails, main.py asks the model once to correct itself; if it still fails, these helpers
produce a safe deterministic message or remove the unverified contacts.
"""
from __future__ import annotations

import json
import re

import evidence as ev
import kavach_business as kb

EMOJI_VERDICT = [("🚨", "LIKELY_SCAM"), ("⚠️", "SUSPICIOUS"), ("⚠", "SUSPICIOUS"), ("✅", "LIKELY_SAFE"),
                 ("❓", "NEED_MORE_INFO")]
# Coarse categories the user actually sees.
CATEGORY = {"SCAM": 3, "LIKELY_SCAM": 3, "SUSPICIOUS": 2, "NEED_MORE_INFO": 1, "LIKELY_SAFE": 1}

FALLBACK = {
    "scam": {
        "te": "🚨 *జాగ్రత్త: ఇది మోసం అయ్యే అవకాశం ఎక్కువ.*\n• లింక్‌లు తెరవకండి, ఎవరికీ OTP లేదా PIN చెప్పకండి, డబ్బు పంపకండి.\n"
              "• డబ్బు పోయినట్లయితే వెంటనే 1930కి కాల్ చేయండి.",
        "hi": "🚨 *सावधान: यह धोखा होने की पूरी संभावना है।*\n• लिंक न खोलें, किसी को OTP या PIN न बताएं, पैसे न भेजें।\n"
              "• अगर पैसे चले गए हैं तो तुरंत 1930 पर कॉल करें।",
        "en": "🚨 *Careful: this is very likely a scam.*\n• Don't open links, don't share any OTP or PIN, and don't send money.\n"
              "• If you have lost money, call 1930 right away.",
    },
    "suspicious": {
        "te": "⚠️ *ఇది అనుమానాస్పదంగా ఉంది.*\n• అధికారిక యాప్ లేదా బ్రాంచ్ ద్వారా నిర్ధారించుకునే వరకు ఏమీ చేయకండి.",
        "hi": "⚠️ *यह संदिग्ध लगता है।*\n• आधिकारिक ऐप या शाखा से पुष्टि होने तक कुछ न करें।",
        "en": "⚠️ *This looks suspicious.*\n• Don't act on it until you've checked through the official app or branch.",
    },
}


def verdict_from_reply(reply: str) -> str | None:
    head = (reply or "").strip()[:12]
    for emoji, verdict in EMOJI_VERDICT:
        if emoji in head:
            return verdict
    return None


def too_lenient(verdict: str | None, floor: str | None) -> bool:
    if not floor:
        return False
    if not verdict:
        return True
    return CATEGORY.get(verdict, 0) < CATEGORY.get(floor, 0)


def correction_prompt(evidence: dict, lenient: bool, bad_contacts: list[str]) -> str:
    lines = ["KAVACH SAFETY CHECK. Rewrite your last reply to the user and fix these problems:"]
    if lenient:
        flags = [f"- {f['finding']} Fact: {f['fact']}" for f in evidence.get("red_flags", [])
                 if f["severity"] in ("high", "critical", "medium")]
        lines.append(f"* Kavach's fixed rules found these red flags, so the verdict must be at least "
                     f"{evidence.get('verdict_floor')} (start the reply with 🚨 for SCAM or LIKELY_SCAM, "
                     f"⚠️ for SUSPICIOUS):")
        lines += flags[:4]
        lines.append("  Use these red flags as your reasons, and call record_verdict again with the corrected verdict.")
    if bad_contacts:
        lines.append("* Remove these websites/phone numbers; Kavach has not verified them: " + ", ".join(bad_contacts)
                     + ". Do not replace them with other numbers or sites. For a bank, say: call the number printed "
                       "on the back of your card or in your passbook.")
    lines.append("Reply with the full corrected message only, in the same language and format.")
    return "\n".join(lines)


def fallback_reply(language: str, floor: str) -> str:
    kind = "scam" if CATEGORY.get(floor, 0) >= 3 else "suspicious"
    return FALLBACK[kind].get(language or "en", FALLBACK[kind]["en"])


def scrub(reply: str, bad_contacts: list[str]) -> str:
    for item in bad_contacts:
        if re.fullmatch(r"\+?\d+", item):
            digits = item[-10:] if item.startswith("+91") else item
            pattern = (r"(?:\+?91[\s-]?)?" if item.startswith("+91") else "") + r"[\s-]?".join(digits)
        else:
            pattern = r"(?:https?://)?(?:[a-z0-9-]+\.)*" + re.escape(item) + r"(?:/[^\s]*)?"
        reply = re.sub(pattern, "[—]", reply, flags=re.I)
    return reply


def context_text(prompt_with_sheet: str, messages: list) -> str:
    """Everything Kavach saw: the user's message, the evidence sheet and every tool result (not the model's own text)."""
    parts = [prompt_with_sheet]
    for msg in messages or []:
        if msg.get("role") != "user":
            continue
        for block in msg.get("content", []):
            if "text" in block:
                parts.append(block["text"])
            elif "toolResult" in block:
                parts.append(json.dumps(block["toolResult"].get("content", []), ensure_ascii=False, default=str))
    return "\n".join(parts)


def sheet_for_model(evidence: dict) -> str:
    keep = ["image_findings", "extracted", "domain_checks", "community_reports", "red_flags", "genuine_signals",
            "matched_playbooks", "verdict_floor", "suggested_actions"]
    sheet = {k: evidence.get(k) for k in keep}
    if evidence.get("product_lookup"):
        sheet["product_lookup"] = evidence["product_lookup"]
    if evidence.get("business_check"):
        sheet["business_check"] = kb.for_model(evidence["business_check"])
        sheet["buttons_after_reply"] = evidence.get("buttons_after_reply") or []
    return json.dumps(sheet, ensure_ascii=False, indent=1, default=str)


def final_verdict(model_verdict: str | None, floor: str | None) -> str:
    return ev.more_severe(model_verdict, floor) or "NEED_MORE_INFO"
