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
    if evidence.get("doctor_request"):
        sheet["doctor_request"] = evidence["doctor_request"]
    if evidence.get("business_check"):
        sheet["business_check"] = kb.for_model(evidence["business_check"])
    return json.dumps(sheet, ensure_ascii=False, indent=1, default=str)


def final_verdict(model_verdict: str | None, floor: str | None) -> str:
    return ev.more_severe(model_verdict, floor) or "NEED_MORE_INFO"


# ----------------------------------------------------------------------------- talk about buttons

# Kavach's code sends buttons and lists with their own instructions, in the person's language. A reply that
# says "tap the button below" when nothing follows leaves an elderly user looking for a button that isn't there,
# so lines that point at buttons are removed. Warnings such as "don't tap any link or button" are kept.
_TAP = r"(tap|click|press|select|choose|pick|ట్యాప్|టాప్|నొక్క|క్లిక్|ఎంచుకో|టచ్|टैप|दबा|क्लिक|चुन)"
_POINTER = r"(button|below|list\b|menu|బటన్|క్రింద|కింద|జాబితా|లిస్ట్|మెనూ|बटन|नीचे|सूची|लिस्ट|मेनू)"
_NOT = (r"(don'?t|do not|never|avoid|వద్దు|చేయకండి|చేయవద్దు|నొక్కకండి|తెరవకండి|ఇవ్వకండి|పంపకండి|చెప్పకండి|"
        r"मत|न करें|न दबाएँ|न खोलें|नहीं)")
_QUOTE = r"(?<!\w)['‘\"“][^'’\"”\n]{2,40}['’\"”](?!\w)"  # a quoted label, not the ' in "it's"
_QUOTED_BELOW = _QUOTE + r"\s*(below|క్రింద|కింద|नीचे)"


def strip_button_talk(reply: str) -> str:
    """Drop lines that tell the person to tap a button or pick from a list, and renumber what is left."""
    lines = (reply or "").split("\n")
    drop = []
    for line in lines:
        low = line.lower()
        outside_quotes = re.sub(_QUOTE, " ", low)
        pointing = ((re.search(_TAP, low) and re.search(_POINTER, low)) or re.search(_QUOTED_BELOW, low)
                    or (re.search(_QUOTE, low) and re.search(_TAP, outside_quotes)))  # "Tap 'My real policy'"
        drop.append(bool(pointing) and not re.search(_NOT, low))
    # A heading ("What to do now?") whose every step was about buttons goes too.
    for i, line in enumerate(lines):
        if drop[i] or not _is_heading(line):
            continue
        block = []
        for j in range(i + 1, len(lines)):
            if not lines[j].strip() or _is_heading(lines[j]):
                break
            block.append(j)
        if block and all(drop[j] for j in block):
            drop[i] = True
    out, n = [], 0
    for line, gone in zip(lines, drop):
        if gone:
            continue
        m = re.match(r"^(\s*)(\d+)([.)])\s", line)
        if m:  # keep "1. 2. 3." in order after removals
            n += 1
            line = f"{m.group(1)}{n}{m.group(3)} " + line[m.end():]
        elif line.strip() and not line.lstrip().startswith(("•", "-")):
            n = 0
        out.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return text or (reply or "").strip()


def _is_heading(line: str) -> bool:
    bare = line.strip().strip("*_ ")
    return 0 < len(bare) <= 40 and bare[-1:] in ("?", ":", "：") and not re.match(r"^\d+[.)]", bare)


# ----------------------------------------------------------------------------- family alert, in code

# The person speaking about themselves ("they called me", "నాకు కాల్ వచ్చింది", "मुझे कॉल आया"). "we"/"us" are left
# out: scam texts say "we have registered a case".
_FIRST_PERSON = r"\b(me|my|i|i'm|im|i am)\b|నాకు|నన్ను|నేను|నా |मुझे|मैं|मेरा|मेरे|मेरी"
_ALERT_CLAIM = r"inform|alert|told|notified|తెలియజేశ|హెచ్చరిక పంప|సమాచారం ఇచ్చ|बता दिया|सूचित|अलर्ट"
DANGER_RULES = {
    "digital_arrest": "may be on a call with someone pretending to be police or CBI (a \"digital arrest\" scam)",
    "authority_asks_money": "is being asked for money by someone claiming to be an official",
    "authority_upi": "is being asked to pay an official by UPI, which real officials never do",
    "remote_access_app": "is being asked to install a screen-sharing app, which lets a scammer see bank OTPs",
}


def danger_now(prompt: str, evidence: dict, final: str, reply: str, guardians: list[dict],
               forwarded: bool) -> str | None:
    """What to tell the family when the person's OWN words show a scam happening to them now, else None.

    Kavach alerts the family in code when the model didn't: the person describes a digital arrest, a demand for
    money by an "official" or a screen-sharing app in their own words, says they are on the call now, or the
    model's reply already claims the family was told. Forwarded messages and news never trigger it.
    """
    if forwarded or final not in ("SCAM", "LIKELY_SCAM"):
        return None
    own_words = prompt.lower()
    if "possible_ongoing_call" in " ".join(evidence.get("suggested_actions") or []):
        return "may be on a call with a scammer right now"
    if re.search(_FIRST_PERSON, own_words):
        for f in evidence.get("red_flags") or []:
            if f.get("rule") in DANGER_RULES and f.get("severity") in ("high", "critical"):
                return DANGER_RULES[f["rule"]]
    names = [g.get("name") for g in guardians if g.get("name")]
    if names and any(n.lower() in (reply or "").lower() for n in names) and re.search(_ALERT_CLAIM, (reply or "").lower()):
        return "may be talking to a scammer right now"
    return None
