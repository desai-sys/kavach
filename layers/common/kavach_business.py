"""Kavach member businesses: check a message's claims against the business's own records, then help the
customer do the real thing.

A business that joins Kavach (a bank, an insurer, a pharmacy, a home-services company...) shares:
  * its official channels: websites, SMS sender IDs and how it takes payments,
  * what it never does (ask for OTPs, take advance payments, cancel policies over WhatsApp...),
  * a small, masked slice of each customer's record: status fields for checks, plus a short summary in
    each language for the customer,
  * a few safe actions Kavach may do for the customer: send the real summary, request a call back,
    report a scam to the fraud team, reserve a refill, show a booking's visit code.

The agent uses this module in evidence.build() and in two tools. The inbound Lambda uses it when a
customer taps one of the buttons Kavach sends after a reply. Every check here is plain code over
records, so nothing in a business verdict comes from the language model.

The four businesses in businesses.json are fictional demo businesses.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import kavach_common as kc

DATA = json.loads((Path(__file__).resolve().parent / "businesses.json").read_text(encoding="utf-8"))
PROFILES: dict[str, dict] = {b["id"]: b for b in DATA["businesses"]}
LANGS = ("en", "te", "hi")
RISKY_VERDICTS = {"SUSPICIOUS", "LIKELY_SCAM", "SCAM"}
MAX_BUTTONS = 3
SIGNAL_TTL_DAYS = 180


def _gap(words: int) -> str:
    """Regex for up to N words between two phrases."""
    return r"(?:\W+\w+){0,%d}?\W+" % words


# ----------------------------------------------------------------------------- claims a message makes

CLAIM_PATTERNS = {
    "account_blocked": [
        r"\b(will|shall) be (temporarily |permanently )?(blocked|suspended|frozen|freezed|deactivated|closed|disabled)\b",
        r"\b(has|have) been (temporarily |permanently )?(blocked|suspended|frozen|deactivated|disabled)\b",
        r"\b(account|a/c|card|yono|net ?banking|upi)\b" + _gap(3) + r"(is |got )?(blocked|suspended|frozen|deactivated)\b",
        r"బ్లాక్ (అవుతుంది|అవుతాయి|చేయబడుతుంది|చేస్తాం|చేస్తారు|అయింది)",
        r"(ब्लॉक|बंद|फ्रीज़) (हो जाएगा|हो जाएगी|कर दिया जाएगा|कर दी जाएगी|हो गया|हो गई|किया जाएगा)",
    ],
    "kyc_pending": [
        r"\b(re-?kyc|e-?kyc|kyc)\b" + _gap(5) + r"(update|updation|expir\w*|pending|incomplete|verif\w*|not updated|suspend\w*|block\w*)",
        r"\b(update|complete|verify|submit|link)\b" + _gap(3) + r"(kyc|pan|aadhaar)\b",
        r"(కేవైసీ|కెవైసి|కేవైసి|kyc).{0,30}(అప్‌డేట్|అప్డేట్|పూర్తి చేయ|గడువు)",
        r"(केवाईसी|kyc).{0,30}(अपडेट|समाप्त|पूरा करें|लंबित)",
    ],
    "policy_lapse": [
        r"\b(lapse|lapsed|lapsing|lapses)\b",
        r"\b(policy|cover|coverage|insurance)\b" + _gap(4)
        + r"(will |shall |has |is |gets? )?(be )?(expire[sd]?|expiring|terminat\w*|cancel\w*|discontinu\w*|stopp?\w*|deactivat\w*)",
        r"(పాలసీ|బీమా|కవరేజ్).{0,30}(రద్దు|ల్యాప్స్|ముగుస్తుంది|ఆగిపోతుంది)",
        r"(पॉलिसी|बीमा|कवर).{0,30}(रद्द|लैप्स|समाप्त|बंद)",
    ],
    "payment_due": [
        r"\b(pay|renew|deposit|clear|settle|recharge)\b" + _gap(5)
        + r"(now|today|immediately|urgently|within|before|to avoid|to continue|to keep|otherwise|else)\b",
        r"\b(premium|bill|amount|payment|dues|emi|balance|charges?|fees?)\b" + _gap(3)
        + r"(is |are |of )?(due|pending|overdue|outstanding|unpaid)\b",
        r"\b(overdue|unpaid|outstanding (dues?|amount|balance)|pending (dues?|payment|amount|premium|bill))\b",
        r"(?:₹|\brs\.?|\binr)\s?[\d,]+(?:\.\d+)?" + _gap(3) + r"(is |are )?(due|pending|payable)\b",
        r"చెల్లించండి|కట్టండి|బకాయి",
        r"भुगतान करें|जमा करें|बकाया|भुगतान लंबित",
    ],
    "refund_or_bonus": [
        r"\b(refund|cashback|cash back|bonus|reward points?|maturity amount|claim amount|rebate|unclaimed)\b",
        r"రిఫండ్|బోనస్|క్యాష్‌బ్యాక్",
        r"रिफंड|बोनस|कैशबैक",
    ],
    "advance_payment": [
        r"\b(advance (payment|amount|fee|money)|pay(ment)? in advance|booking (fee|amount|charges?)|"
        r"token (amount|money|fee)|registration fee|confirmation (fee|amount|charges?)|slot (fee|charges?))\b",
        r"\b(pay|send|transfer)\b" + _gap(6) + r"(to )?confirm (your |the )?(slot|booking|appointment|order)\b",
        r"\badvance\b" + _gap(3) + r"(to|for)\b",
        r"అడ్వాన్స్|ముందుగా (డబ్బు|చెల్లించ)",
        r"एडवांस|अग्रिम|पहले (पैसे|भुगतान)",
    ],
    "booking_cancel": [
        r"\b(slot|booking|appointment|order|service)\b" + _gap(4)
        + r"(will |shall |is |has been |gets? )?(be )?(cancel\w*|released|given to someone else)\b",
        r"\b(else|otherwise|or)\b" + _gap(3) + r"(slot|booking|appointment|order)\b" + _gap(2) + r"cancel\w*",
        r"(బుకింగ్|స్లాట్|ఆర్డర్).{0,25}రద్దు",
        r"(बुकिंग|स्लॉट|ऑर्डर).{0,25}(रद्द|कैंसल)",
    ],
    "debit_alert": [
        r"\b(debited|credited|deducted|withdrawn|spent)\b",
        r"డెబిట్ (అయింది|అయ్యాయి)|కట్ అయ్యాయి|జమ అయ్యాయి",
        r"(डेबिट|क्रेडिट|कट) (हुआ|हुए|हो गए|किया गया)",
    ],
    "delivery_issue": [
        r"\b(delivery|parcel|order|shipment|package|medicines?)\b" + _gap(4)
        + r"(is |has |was )?(failed|pending|on hold|held|stuck|undelivered|returned|could not|couldn't|unable|delayed)\b",
        r"\b(re-?schedule|re-?deliver\w*)\b",
    ],
}
# Phrases that cancel a claim, e.g. "your KYC has been updated" is not a "KYC pending" claim.
CLAIM_UNLESS = {
    "kyc_pending": [r"\b(re-?kyc|e-?kyc|kyc)\b(?:\W+\w+){0,3}?\W+(is|has been|was|got)\W+(successfully\W+)?"
                    r"(complete|completed|done|verified|updated)\b"],
    "refund_or_bonus": [r"\bno[- ]claims? bonus\b", r"\bncb\b"],
    "account_blocked": [r"\b(as|at|on) (per )?your request\b"],
}
_CLAIM_RE = {k: [re.compile(p) for p in v] for k, v in CLAIM_PATTERNS.items()}
_UNLESS_RE = {k: [re.compile(p) for p in v] for k, v in CLAIM_UNLESS.items()}
# Claims that ask the customer to do something; sending them to an unofficial channel for these is a red flag.
ACTION_CLAIMS = {"payment_due", "advance_payment", "kyc_pending", "account_blocked", "policy_lapse",
                 "refund_or_bonus", "booking_cancel", "delivery_issue", "debit_alert"}


def claims_in(text: str) -> list[str]:
    t = (text or "").lower()
    return [c for c, pats in _CLAIM_RE.items()
            if any(p.search(t) for p in pats) and not any(u.search(t) for u in _UNLESS_RE.get(c, []))]


# ----------------------------------------------------------------------------- which business

def _find_alias(text: str, alias: str) -> int | None:
    if alias.isascii():
        m = re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text)
        return m.start() if m else None
    pos = text.find(alias)
    return pos if pos >= 0 else None


def detect(text: str, links: list | None = None, sms_header: str | None = None) -> list[dict]:
    """Member businesses a message mentions or claims to come from, most likely first."""
    t = (text or "").lower()
    header_id = sms_header.split("-")[1].upper() if sms_header and sms_header.count("-") >= 1 else ""
    hits: dict[str, tuple[int, str]] = {}
    for bid, p in PROFILES.items():
        best = None
        for alias in p["aliases"]:
            pos = _find_alias(t, alias.lower())
            if pos is not None and (best is None or pos < best[0]):
                best = (pos, "name")
        if best is None:
            for link in links or []:
                tokens = [x for x in re.split(r"[^a-z0-9]+", link.get("host", "")) if x]
                if any(tok.startswith(bt) or tok.endswith(bt) for bt in p["brand_tokens"] for tok in tokens):
                    best = (t.find(link["host"]) if link["host"] in t else len(t), "website")
                    break
        if header_id and header_id in p.get("sms_headers", []):
            best = (-1, "sms_header")
        if best:
            hits[bid] = best
    return [{"id": bid, "detected_by": how} for bid, (_pos, how) in sorted(hits.items(), key=lambda kv: kv[1][0])]


def find(name: str) -> str | None:
    """Business id for a name the model or user typed ("Nidhira", "kalpavi bank", "dawaghar_pharmacy")."""
    n = re.sub(r"[_\s]+", " ", (name or "").lower()).strip()
    if not n:
        return None
    for bid, p in PROFILES.items():
        names = {bid.replace("_", " "), p["name"].lower(), p["short_name"].lower(), *(a.lower() for a in p["aliases"])}
        if n in names or any(_find_alias(n, a) is not None for a in names if len(a) > 3):
            return bid
    return None


def member_names() -> list[str]:
    return [p["name"] for p in PROFILES.values()]


def action_kinds(business_id: str) -> list[str]:
    return [a["kind"] for a in PROFILES[business_id]["actions"]]


# ----------------------------------------------------------------------------- records

def get_record(business_id: str, phone: str) -> dict | None:
    """The customer's record at a member business, looked up by their own WhatsApp number."""
    item = kc.table("business_records_table").get_item(
        Key={"business_id": business_id, "phone": kc.normalize_phone(phone)}).get("Item")
    return kc.to_jsonable(item) if item else None


def _update_status(business_id: str, phone: str, **fields) -> None:
    names = {"#st": "status", **{f"#{k}": k for k in fields}}
    kc.table("business_records_table").update_item(
        Key={"business_id": business_id, "phone": kc.normalize_phone(phone)},
        UpdateExpression="SET " + ", ".join(f"#st.#{k} = :{k}" for k in fields),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues={f":{k}": kc.clean_for_dynamo(v) for k, v in fields.items()},
    )


def _poss(name: str) -> str:
    """Possessive: \"Kalpavi Bank's\", \"Chamak Home Services'\"."""
    return name + ("'" if name.endswith("s") else "'s")


def _today() -> date:
    return datetime.now(kc.IST).date()


def _parse_day(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (TypeError, ValueError):
        return None


def human_date(value) -> str:
    d = _parse_day(value)
    return f"{d.day} {d:%b %Y}" if d else str(value or "")


def _human_when(value) -> str:
    try:
        dt = datetime.fromisoformat(str(value))
        return f"{dt:%a} {dt.day} {dt:%b}, {dt:%I:%M %p}".replace(" 0", " ")
    except (TypeError, ValueError):
        return str(value or "")


def money(value) -> str:
    """Indian digit grouping: 500000 -> 5,00,000."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return str(value)
    s = str(abs(n))
    if len(s) > 3:
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", s[:-3])
        s = f"{head},{s[-3:]}"
    return ("-" if n < 0 else "") + s


def _amounts(raw: list | None) -> list[float]:
    out = []
    for a in raw or []:
        try:
            out.append(float(str(a).replace(",", "")))
        except ValueError:
            pass
    return out


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1
    except (TypeError, ValueError):
        return False


def _mentions_date(text: str, d: date | None) -> bool:
    if not d:
        return False
    forms = {f"{d.day} {d:%b}".lower(), f"{d.day} {d:%B}".lower(), f"{d:%d} {d:%b}".lower(), d.isoformat(),
             f"{d:%d/%m/%Y}", f"{d:%d-%m-%Y}", f"{d.day}/{d.month}/{d.year}", f"{d:%d/%m/%y}", f"{d:%d-%m-%y}",
             f"{d:%d-%b-%Y}".lower()}
    return any(f in text for f in forms)


# ----------------------------------------------------------------------------- the check

def verify(business_id: str, record: dict | None, text: str, extracted: dict | None = None,
           today: date | None = None, records_available: bool = True) -> dict:
    """Compare what a message claims with the business's rules and this customer's record."""
    p = PROFILES[business_id]
    name, short = p["name"], p["short_name"]
    names = _poss(name)
    ex = extracted or {}
    t = (text or "").lower()
    today = today or _today()
    claims = claims_in(t)
    st = (record or {}).get("status") or {}
    amounts = _amounts(ex.get("amounts_inr"))
    contradictions: list[dict] = []
    confirmations: list[str] = []

    def contra(claim: str, severity: str, finding: str, basis: str = "records") -> None:
        contradictions.append({"claim": claim, "severity": severity, "finding": finding, "basis": basis})

    if record:
        if "account_blocked" in claims and st.get("account_active"):
            contra("account_blocked", "high",
                   f"The message says your account will be (or has been) blocked, but {names} records show "
                   f"account {st.get('account', '')} is active with no block or freeze.")
        if "kyc_pending" in claims and st.get("kyc_complete"):
            until = f", valid until {human_date(st['kyc_valid_until'])}" if st.get("kyc_valid_until") else ""
            contra("kyc_pending", "high",
                   f"The message says your KYC needs updating, but {names} records show your KYC is complete{until}.")
        if "policy_lapse" in claims and st.get("policy_active") and st.get("active_until"):
            end = _parse_day(st["active_until"])
            if _mentions_date(t, end) or (end and (end - today).days <= 30):
                confirmations.append(f"{names} records agree: policy {st.get('policy', '')} is active until "
                                     f"{human_date(end)}.")
            else:
                contra("policy_lapse", "high",
                       f"The message says your policy will lapse or be cancelled, but {names} records show policy "
                       f"{st.get('policy', '')} is active until {human_date(end)}.")
        if ("payment_due" in claims or "advance_payment" in claims) and "amount_due_now" in st:
            due, next_amount = st["amount_due_now"], st.get("next_due_amount")
            next_date = _parse_day(st.get("next_due_date"))
            if due and any(_same(a, due) for a in amounts):
                confirmations.append(f"Matches {names} records: ₹{money(due)} is due now.")
            elif next_amount and any(_same(a, next_amount) for a in amounts):
                if _mentions_date(t, next_date) or (next_date and (next_date - today).days <= 45):
                    confirmations.append(f"Matches {names} records: the next payment of ₹{money(next_amount)} "
                                         f"is due on {human_date(next_date)}.")
                else:
                    contra("payment_due", "high",
                           f"The amount matches your next payment to {short}, but {names} records show it is not due "
                           f"until {human_date(next_date)}. Scammers sometimes know real amounts from leaked data.")
            elif due:
                if amounts:
                    contra("payment_due", "medium", f"The message asks for ₹{money(amounts[0])}, but {names} "
                                                    f"records show ₹{money(due)} due.")
            else:
                nxt = (f" The next payment is ₹{money(next_amount)} on {human_date(next_date)}."
                       if next_amount and next_date else "")
                contra("payment_due", "high",
                       f"The message asks for a payment, but {names} records show nothing is due now.{nxt}")
        if "refund_or_bonus" in claims and st.get("refund_pending") is False:
            contra("refund_or_bonus", "high", f"The message talks about a refund, bonus or reward, but {names} "
                                              f"records show nothing pending for you.")
        if "booking_cancel" in claims and st.get("booking_status") == "confirmed":
            contra("booking_cancel", "high",
                   f"The message says your booking will be cancelled, but {names} records show your "
                   f"{st.get('service', 'booking')} on {_human_when(st.get('booking_at'))} is confirmed.")
        if "debit_alert" in claims and isinstance(st.get("transactions"), list) and amounts:
            hit = next((tx for tx in st["transactions"] if any(_same(a, tx.get("amount")) for a in amounts)), None)
            if hit:
                confirmations.append(f"Matches {names} records: ₹{money(hit['amount'])} {hit.get('type', '')} on "
                                     f"{human_date(hit.get('date'))} ({hit.get('detail', '')}).")
            else:
                contra("debit_alert", "medium",
                       f"The message mentions ₹{money(amounts[0])} going in or out, but {names} records show no "
                       f"such transaction on your account.")
        if "delivery_issue" in claims and st.get("order_out_for_delivery") is False:
            contra("delivery_issue", "medium", f"The message talks about a delivery problem, but {names} records "
                                               f"show no order of yours out for delivery.")

    # The business's own published rules apply whether or not we found a record.
    if "advance_payment" in claims and (p.get("policies") or {}).get("no_advance_payment"):
        contra("advance_payment", "high", f"{name} never asks for advance payment. {p['how_you_pay']}.", "policy")

    official = set(p["official_domains"])
    unofficial: list[str] = []
    if set(claims) & ACTION_CLAIMS:
        unofficial += [u for u in ex.get("upi_ids", []) if u not in set(p.get("official_upi_ids", []))]
        unofficial += [link["host"] for link in ex.get("links", []) if link.get("domain") not in official]
    header = ex.get("sms_header") or ""
    official_header = header if header.count("-") >= 1 and header.split("-")[1].upper() in p.get("sms_headers", []) else None

    if record:
        note = None
    elif records_available:
        note = f"No {name} record is linked to this WhatsApp number, so the claim could not be checked against records."
    else:
        note = f"{names} records could not be reached just now, so only its published rules were checked."
    return {
        "business_id": business_id,
        "business": name,
        "kind": p["kind"],
        "is_customer": bool(record),
        "record_facts": ((record or {}).get("summary") or {}).get("en", []),
        "note": note,
        "business_rules": [f"{short} never {n}." for n in p.get("never", [])] + [p["how_you_pay"] + "."],
        "official_websites": p["official_domains"],
        "official_sms_sender_ids": p.get("sms_headers", []),
        "claims_found": claims,
        "contradictions": contradictions,
        "confirmations": confirmations,
        "unofficial_channels": unofficial,
        "official_sms_header": official_header,
    }


def red_flags(check: dict) -> list[dict]:
    """Red flags (evidence.py format, without ids) from a business check."""
    p = PROFILES[check["business_id"]]
    source = f"{check['business']} (Kavach member business)"
    flags = []
    for c in check["contradictions"]:
        from_records = c["basis"] == "records"
        flags.append({
            "rule": "contradicts_records" if from_records else "against_business_policy",
            "severity": c["severity"],
            "finding": c["finding"],
            "fact": (f"Checked just now against {_poss(check['business'])} own customer records." if from_records
                     else f"Published rule of {check['business']}."),
            "source": source,
        })
    if check["unofficial_channels"]:
        where = ", ".join(check["unofficial_channels"][:3])
        flags.append({
            "rule": "unofficial_channel",
            "severity": "high",
            "finding": f"The message is about {check['business']} but sends you to {where}, which is not an official "
                       f"{p['short_name']} channel.",
            "fact": f"{p['how_you_pay']}. Official website: {', '.join(p['official_domains'])}.",
            "source": source,
        })
    return flags


def genuine_signals(check: dict) -> list[str]:
    out = list(check["confirmations"])
    if check.get("official_sms_header"):
        out.append(f"The SMS sender ID {check['official_sms_header']} is {_poss(check['business'])} registered sender ID.")
    return out


def for_model(check: dict) -> dict:
    """The business check as the model sees it on the evidence sheet."""
    keep = ["business", "kind", "detected_by", "is_customer", "record_facts", "note", "business_rules",
            "official_websites", "claims_found", "contradictions", "confirmations"]
    out = {k: check.get(k) for k in keep if check.get(k) not in (None, [], "")}
    out["contradictions"] = [c["finding"] for c in check.get("contradictions", [])]
    return out


# ----------------------------------------------------------------------------- buttons and actions

STRINGS = {
    "buttons_text": {
        "en": "{name} is a Kavach member. What would you like to do?",
        "te": "{name} కవచ్ సభ్య సంస్థ. మీరు ఏమి చేయాలనుకుంటున్నారు?",
        "hi": "{name} कवच की सदस्य संस्था है। आप क्या करना चाहेंगे?",
    },
    "summary_header": {
        "en": "📄 From {names} own records, checked just now:",
        "te": "📄 {name} సొంత రికార్డుల ప్రకారం (ఇప్పుడే చూశాను):",
        "hi": "📄 {name} के अपने रिकॉर्ड के अनुसार (अभी जाँचा):",
    },
    "email_copy": {
        "en": "A copy has been emailed to you.",
        "te": "దీని కాపీ మీ ఈమెయిల్‌కు పంపాను.",
        "hi": "इसकी कॉपी आपके ईमेल पर भेज दी है।",
    },
    "visit_code": {
        "en": "🔐 Visit code: *{code}*. {pro} will tell you this code at the door. Don't open the door to, or pay, "
              "anyone who doesn't know it.",
        "te": "🔐 విజిట్ కోడ్: *{code}*. {pro} తలుపు వద్ద ఈ కోడ్ చెబుతారు. ఈ కోడ్ తెలియని వారికి తలుపు తీయకండి, "
              "డబ్బు ఇవ్వకండి.",
        "hi": "🔐 विज़िट कोड: *{code}*। {pro} दरवाज़े पर यह कोड बताएँगे। जिसे यह कोड न पता हो, उसके लिए दरवाज़ा न "
              "खोलें, उसे पैसे न दें।",
    },
    "refill_ok": {
        "en": "✅ Reserved with {name}: {item}. It will reach you by {date}. Pay about ₹{amount} to the delivery "
              "person after you receive it. {short} never asks for payment in advance.",
        "te": "✅ {name}లో రిజర్వ్ చేశాను: {item}. {date} లోపు మీకు అందుతుంది. మందులు అందిన తర్వాతే డెలివరీ "
              "వ్యక్తికి సుమారు ₹{amount} చెల్లించండి. {short} ఎప్పుడూ ముందుగా డబ్బు అడగదు.",
        "hi": "✅ {name} में रिज़र्व कर दिया: {item}। {date} तक आपके पास पहुँच जाएगा। दवा मिलने के बाद ही डिलीवरी "
              "वाले को लगभग ₹{amount} दें। {short} कभी पहले से पैसे नहीं माँगता।",
    },
    "callback_ok": {
        "en": "✅ Done. {name} will call you within {hours} hours{from_1600}. Anyone else who calls about this and asks "
              "for money, an OTP or an app is not {short}.",
        "te": "✅ పూర్తయింది. {name} {hours} గంటల్లో{from_1600} మీకు కాల్ చేస్తుంది. దీని గురించి డబ్బు, OTP లేదా యాప్ "
              "అడిగే వేరే ఎవరైనా {short} కాదు.",
        "hi": "✅ हो गया। {name} {hours} घंटे के अंदर{from_1600} आपको कॉल करेगा। इस बारे में पैसे, OTP या ऐप माँगने "
              "वाला कोई और {short} नहीं है।",
    },
    "from_1600": {
        "en": " from a number starting with 1600",
        "te": " 1600తో మొదలయ్యే నంబర్ నుంచి",
        "hi": " 1600 से शुरू होने वाले नंबर से",
    },
    "report_ok": {
        "en": "🚫 Reported to {names} fraud team with the scammer's details. Thank you, this helps protect other "
              "customers too.",
        "te": "🚫 మోసగాడి వివరాలతో {name} ఫ్రాడ్ టీమ్‌కు రిపోర్ట్ చేశాను. ధన్యవాదాలు, ఇది ఇతర కస్టమర్లను కూడా "
              "కాపాడుతుంది.",
        "hi": "🚫 ठग की जानकारी के साथ {name} की फ्रॉड टीम को रिपोर्ट कर दिया। धन्यवाद, इससे दूसरे ग्राहक भी "
              "सुरक्षित रहेंगे।",
    },
    "no_record": {
        "en": "I couldn't find a {name} record linked to this WhatsApp number.",
        "te": "ఈ వాట్సాప్ నంబర్‌తో లింక్ అయిన {name} రికార్డు దొరకలేదు.",
        "hi": "इस व्हाट्सऐप नंबर से जुड़ा {name} का कोई रिकॉर्ड नहीं मिला।",
    },
    "expired": {
        "en": "That option is no longer available. Forward the message again to check it.",
        "te": "ఆ ఆప్షన్ ఇప్పుడు అందుబాటులో లేదు. మళ్ళీ చెక్ చేయడానికి మెసేజ్‌ను మళ్ళీ ఫార్వర్డ్ చేయండి.",
        "hi": "यह विकल्प अब उपलब्ध नहीं है। जाँच के लिए मैसेज फिर से फ़ॉरवर्ड करें।",
    },
}


def _t(key: str, lang: str | None, **kw) -> str:
    options = STRINGS[key]
    return (options.get(lang or "en") or options["en"]).format(**kw)


def buttons_for(business_id: str, verdict: str | None, lang: str | None, incident_id: str | None = None,
                is_customer: bool = True) -> list[dict]:
    """Up to three quick-reply buttons for this business. "Report this scam" only appears for risky verdicts;
    record-based actions only appear for the business's own customers."""
    p = PROFILES.get(business_id)
    if not p:
        return []
    lang = lang if lang in LANGS else "en"
    normal = [a for a in p["actions"] if a["kind"] != "report"
              and (is_customer or a["kind"] not in ("summary", "booking", "refill"))]
    report = [a for a in p["actions"] if a["kind"] == "report"]
    chosen = normal[:MAX_BUTTONS - 1] + report[:1] if (verdict in RISKY_VERDICTS and report) else normal[:MAX_BUTTONS]
    ref = incident_id or "-"
    return [{"id": f"BIZ|{business_id}|{a['id']}|{ref}", "title": a["title"].get(lang) or a["title"]["en"]}
            for a in chosen]


def buttons_text(business_id: str, lang: str | None) -> str:
    return _t("buttons_text", lang, name=PROFILES[business_id]["name"])


def _own_incident(incident_id: str | None, phone: str) -> dict | None:
    """The incident, but only if it belongs to this customer (button payloads are not trusted)."""
    if not incident_id or incident_id == "-":
        return None
    try:
        inc = kc.get_incident(incident_id)
    except Exception as exc:
        print(f"Incident lookup failed: {exc!r}")
        return None
    return inc if inc and kc.normalize_phone(inc.get("phone", "")) == phone else None


def _desk_email(p: dict) -> str | None:
    c = kc.cfg()
    return p.get("desk_email") or c.get("business_desk_email") or c.get("bank_fraud_email")


def _mask(phone: str) -> str:
    d = kc.phone_digits(phone)
    return f"+{d[:4]}XXXX{d[-4:]}" if len(d) >= 10 else phone


def perform_action(user: dict, business_id: str, action: str, incident_id: str | None = None,
                   send: bool = True) -> dict:
    """Do one official action for the customer and (by default) send them the confirmation on WhatsApp.

    action is an action id from the profile ("policy", "callback") or a kind ("summary", "report").
    Records are always looked up by the customer's own number, never by anything in the button payload.
    """
    p = PROFILES.get(business_id)
    lang = user.get("language") if user.get("language") in LANGS else "en"
    phone = kc.normalize_phone(user.get("phone", ""))
    spec = next((a for a in (p or {}).get("actions", []) if action in (a["id"], a["kind"])), None)
    if not p or not spec or not phone:
        text = _t("expired", lang)
        if send and phone:
            kc.wa_text(phone, text)
        return {"done": False, "error": "unknown business or action",
                "available_actions": action_kinds(business_id) if p else []}

    name, short, kind = p["name"], p["short_name"], spec["kind"]
    incident = _own_incident(incident_id, phone)
    customer = user.get("name") or "A customer"
    emailed = False

    if kind in ("summary", "booking", "refill"):
        record = get_record(business_id, phone)
        if not record:
            text = _t("no_record", lang, name=name)
        elif kind == "refill":
            st = record.get("status") or {}
            _update_status(business_id, phone, refill_reserved=True, refill_reserved_at=kc.now_iso())
            text = _t("refill_ok", lang, name=name, short=short, item=st.get("refill_item", ""),
                      date=human_date(st.get("refill_due")), amount=money(st.get("refill_amount", 0)))
        else:
            summary = record.get("summary") or {}
            lines = summary.get(lang) or summary.get("en") or []
            text = _t("summary_header", lang, name=name, names=_poss(name)) + "\n" + "\n".join(f"• {line}" for line in lines)
            if user.get("email"):
                try:
                    en_lines = summary.get("en") or lines
                    kc.email_send([user["email"]], f"Your {name} details (checked by Kavach)", kc.email_shell(
                        f"Your {html.escape(name)} details",
                        "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in en_lines) + "</ul>"
                        f"<p style='color:#78716c'>From {html.escape(_poss(name))} own records, {kc.now_ist_str()}. "
                        f"{html.escape(name)} will never ask for an OTP, PIN or password.</p>"),
                        "\n".join(en_lines))
                    emailed = True
                    text += "\n" + _t("email_copy", lang)
                except Exception as exc:
                    print(f"Summary email failed: {exc!r}")
            if kind == "booking" and record.get("visit_code"):
                text += "\n\n" + _t("visit_code", lang, code=record["visit_code"],
                                    pro=(record.get("status") or {}).get("professional", ""))
    elif kind == "callback":
        body = (f"{customer} ({phone}) asked {name} to call them back"
                + (f" about a suspicious message (Kavach incident {incident['incident_id']}: "
                   f"{incident.get('check_summary', '')})" if incident else "")
                + f". Please call within {p.get('callback_hours', 4)} hours from an official number.")
        kc.email_send([_desk_email(p)], f"Kavach call-back request: {customer}",
                      kc.email_shell("Call-back request", f"<p>{html.escape(body)}</p>"), body)
        text = _t("callback_ok", lang, name=name, short=short, hours=p.get("callback_hours", 4),
                  from_1600=_t("from_1600", lang) if p.get("regulated_bfsi") else "")
    elif kind == "report":
        inc = incident or {}
        rows = [("Kavach incident", inc.get("incident_id", "not linked")),
                ("Reported by", f"{customer} ({_mask(phone)}), {user.get('district') or 'district unknown'}"),
                ("Verdict", inc.get("verdict", "")),
                ("What the message claimed", ", ".join(inc.get("business_claims", []) or []) or "-"),
                ("Scammer identifiers", ", ".join(inc.get("scam_identifiers", []) or []) or "-"),
                ("Summary", inc.get("check_summary", "")),
                ("Received", kc.now_ist_str())]
        table_html = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#78716c'>{html.escape(k)}</td>"
                             f"<td style='padding:4px 0'>{html.escape(str(v))}</td></tr>" for k, v in rows)
        kc.email_send([_desk_email(p)], f"Kavach impersonation report: {name}",
                      kc.email_shell(f"Someone is impersonating {html.escape(name)}",
                                     f"<table role='presentation'>{table_html}</table>"
                                     "<p>Kavach warned the customer. Consider blocking the identifiers above and "
                                     "warning other customers.</p>"),
                      "\n".join(f"{k}: {v}" for k, v in rows))
        text = _t("report_ok", lang, name=name, names=_poss(name))
    else:
        text = _t("expired", lang)

    try:
        record_signal(business_id, "action", action=kind, district=user.get("district", ""),
                      incident_id=incident["incident_id"] if incident else None)
    except Exception as exc:
        print(f"Business signal not saved: {exc!r}")
    if incident:
        try:
            kc.append_incident_event(incident["incident_id"], f"{name}: customer used '{kind}'")
        except Exception as exc:
            print(f"Incident event not saved: {exc!r}")
    if send:
        kc.wa_text(phone, text)
    return {"done": True, "business": name, "action": kind, "message_sent_to_user": text, "emailed_copy": emailed}


# ----------------------------------------------------------------------------- signals back to the business

def record_signal(business_id: str, kind: str, **fields) -> None:
    """Anonymous event for the business's fraud-intelligence report (no customer phone numbers)."""
    now = kc.now_iso()
    kc.table("business_signals_table").put_item(Item=kc.clean_for_dynamo({
        "business_id": business_id, "signal_id": f"{now}#{uuid.uuid4().hex[:8]}", "kind": kind,
        "created_at": now, "expires_at": int(time.time()) + SIGNAL_TTL_DAYS * 24 * 3600, **fields,
    }))


# ----------------------------------------------------------------------------- demo data

_PLACEHOLDER = re.compile(r"\{(iso:)?(today([+-]\d+)?|next_saturday|visit_code)\}")


def _next_saturday(today: date) -> date:
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


def demo_record(business_id: str, phone: str, customer_name: str = "", today: date | None = None,
                visit_code: str | None = None) -> dict:
    """The demo record from businesses.json with dates filled in relative to today."""
    today = today or _today()
    phone = kc.normalize_phone(phone)
    code = visit_code or str(int(hashlib.sha256(f"{business_id}{phone}".encode()).hexdigest(), 16) % 9000 + 1000)

    def fill(value):
        if isinstance(value, str):
            def sub(m):
                if m.group(2) == "visit_code":
                    return code
                d = _next_saturday(today) if m.group(2) == "next_saturday" else today + timedelta(days=int(m.group(3) or 0))
                return d.isoformat() if m.group(1) else human_date(d)
            return _PLACEHOLDER.sub(sub, value)
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fill(v) for v in value]
        return value

    record = fill(PROFILES[business_id]["demo_record"])
    return {"business_id": business_id, "phone": phone, "customer_name": customer_name, **record,
            "updated_at": kc.now_iso()}
