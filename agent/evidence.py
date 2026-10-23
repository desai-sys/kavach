"""Evidence-first checks.

Before the model sees a message, plain code:
  1. reads any image/PDF once (vision model) and keeps its findings,
  2. extracts links, phone numbers, UPI IDs and amounts with regular expressions,
  3. runs the domain and community-report checks in parallel,
  4. applies fixed red-flag rules built on verified Indian facts,
  5. computes a verdict floor: the least severe verdict the reply may give.

The model then explains this evidence; main.py enforces the floor afterwards.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import kavach_common as kc
from tools.investigate import (OFFICIAL_DOMAINS, _host_of, _normalize_identifier, _registrable, analyze_media,
                               check_domain, check_reputation, search_scam_playbooks)

SEVERITY_ORDER = ["low", "medium", "high", "critical"]
VERDICT_ORDER = ["LIKELY_SAFE", "NEED_MORE_INFO", "SUSPICIOUS", "LIKELY_SCAM", "SCAM"]
FLOOR_FOR_SEVERITY = {"critical": "SCAM", "high": "LIKELY_SCAM", "medium": "SUSPICIOUS"}

SAFE_DOMAINS = {"cybercrime.gov.in", "sancharsaathi.gov.in", "rbi.org.in", "npci.org.in", "sebi.gov.in",
                "incometax.gov.in", "uidai.gov.in", "parivahan.gov.in", "indiapost.gov.in"}
SAFE_NUMBERS = {"1930", "112", "100"}  # cyber-fraud helpline, emergency, police
OFFICIAL_REGISTRABLE = {d for domains in OFFICIAL_DOMAINS.values() for d in domains}

MAX_LINKS = 5
MAX_IDENTIFIERS = 10

# ----------------------------------------------------------------------------- extraction

_TLDS = ("com|in|org|net|co|info|xyz|top|shop|click|live|buzz|icu|cyou|sbs|rest|monster|online|site|vip|cc|ws|tk|"
         "ml|ga|cf|gq|lol|store|fun|life|today|app|link|me|io|ly|gd|at|sbi|bank|gov|nic|us|uk|cn|ru|pw|biz|club|"
         "win|work|support|help|services|service|page|website|space|tech|world|asia|ai")
URL_RE = re.compile(
    r"(?<![@\w.-])(?:https?://[^\s<>\"'()]+|(?:www\.)?(?:[a-z0-9-]+\.)+(?:" + _TLDS + r")(?![a-z0-9@-])(?!\.[a-z0-9])(?:/[^\s<>\"'()]*)?)",
    re.I)
MOBILE_RE = re.compile(r"(?<![\d+])(?:\+?91[\s-]?|0)?([6-9]\d{4}[\s-]?\d{5})(?!\d)")
SERIES_RE = re.compile(r"(?<!\d)((?:1600|1800|1860)[\s-]?\d{3}[\s-]?\d{3,4}|140\d{7})(?!\d)")
UPI_RE = re.compile(r"(?<![\w.@-])([a-z0-9][\w.\-]{1,255})@([a-z][a-z0-9]{1,30})(?![\w.@-])", re.I)
AMOUNT_RE = re.compile(r"(?:₹|\brs\.?|\binr)\s?([\d,]+(?:\.\d+)?)", re.I)
HEADER_RE = re.compile(r"\b([A-Z]{2})-([A-Z0-9]{3,9})(?:-([PSTG]))?\b")


def _strip_url(u: str) -> str:
    return u.rstrip(".,;:!?)]}*_'\"")


def extract(text: str) -> dict:
    text = text or ""
    links, seen = [], set()
    for m in URL_RE.finditer(text):
        url = _strip_url(m.group(0))
        host = _host_of(url)
        if not host or host in seen:
            continue
        seen.add(host)
        links.append({"url": url, "host": host, "domain": _registrable(host)})
    mobiles = sorted({"+91" + re.sub(r"\D", "", m.group(1)) for m in MOBILE_RE.finditer(text)})
    series = sorted({re.sub(r"\D", "", m.group(1)) for m in SERIES_RE.finditer(text)})
    upis = sorted({f"{a}@{b}".lower() for a, b in UPI_RE.findall(text)})
    amounts = [a.replace(",", "") for a in AMOUNT_RE.findall(text)]
    header = HEADER_RE.search(text)
    return {
        "links": links[:MAX_LINKS],
        "mobile_numbers": mobiles,
        "special_numbers": series,
        "upi_ids": upis,
        "amounts_inr": amounts,
        "sms_header": header.group(0) if header else None,
        "sms_header_type": {"P": "promotional", "S": "service", "T": "transactional", "G": "government"}.get(
            header.group(3)) if header and header.group(3) else None,
    }


# ----------------------------------------------------------------------------- keyword groups

def _has(text: str, words: list[str]) -> list[str]:
    hits = []
    for w in words:
        if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text) if w.isascii() else w in text:
            hits.append(w)
    return hits


INSTITUTION = ["bank", "sbi", "hdfc", "icici", "axis", "kotak", "pnb", "canara", "baroda", "yono", "rbi",
               "reserve bank", "kyc", "pan card", "aadhaar", "electricity", "power supply", "current bill", "discom",
               "police", "cbi", "enforcement directorate", "customs", "narcotics", "ncb", "trai", "income tax",
               "court", "india post", "fedex", "dhl", "blue dart", "courier", "epfo", "pension", "telecom",
               "బ్యాంక్", "బ్యాంకు", "పోలీస్", "కరెంట్", "విద్యుత్", "సీబీఐ", "కస్టమ్స్", "ఆధార్",
               "बैंक", "पुलिस", "बिजली", "सीबीआई", "कस्टम", "आधार"]
AUTHORITY = ["police", "cbi", "enforcement directorate", "ed officer", "customs", "narcotics", "ncb", "trai",
             "court", "judge", "crime branch", "cyber cell", "supreme court", "rbi officer",
             "పోలీస్", "సీబీఐ", "కస్టమ్స్", "కోర్టు", "पुलिस", "सीबीआई", "कस्टम", "कोर्ट", "अदालत"]
COERCION = ["digital arrest", "arrest warrant", "you will be arrested", "video call", "skype", "money laundering",
            "do not tell", "don't tell", "dont tell", "stay on the call", "stay on call", "safe account",
            "verification account", "rbi account", "case registered against you", "drugs in your parcel",
            "parcel seized", "your aadhaar is linked", "your aadhaar is misused",
            "అరెస్ట్", "వీడియో కాల్", "ఎవరికీ చెప్పొద్దు", "ఎవరికీ చెప్పవద్దు", "మనీ లాండరింగ్",
            "गिरफ्तार", "डिजिटल अरेस्ट", "वीडियो कॉल", "किसी को मत बताना", "किसी को मत बताओ", "मनी लॉन्ड्रिंग"]
REMOTE_APPS = ["anydesk", "teamviewer", "quicksupport", "rustdesk", "airdroid", "screen share", "screen sharing",
               "remote access"]
RECEIVE_WORDS = ["receive", "refund", "cashback", "prize", "reward", "received", "credit you", "get money",
                 "పొందడానికి", "రిఫండ్", "पाने के लिए", "रिफंड"]
PIN_WORDS = ["upi pin", "enter pin", "enter your pin", "scan the qr", "scan qr", "scan this qr", "qr code",
             "యూపీఐ పిన్", "పిన్", "यूपीआई पिन", "पिन डालें", "क्यूआर"]
PRIZE_WORDS = ["lottery", "kbc", "kaun banega crorepati", "lucky draw", "you have won", "you won", "winner",
               "లాటరీ", "लॉटरी", "इनाम"]
FEE_WORDS = ["processing fee", "registration fee", "gst", "tax", "charges", "fee", "pay rs", "pay ₹", "deposit"]
RETURNS_WORDS = ["guaranteed return", "guaranteed profit", "assured return", "double your money", "daily profit",
                 "100% profit", "risk free", "risk-free"]
INVEST_WORDS = ["invest", "investment", "trading", "stock", "ipo", "crypto", "share market", "usdt"]
PAID_WORDS = ["i paid", "i have paid", "already paid", "i sent", "i have sent", "already sent", "i transferred",
              "transferred", "money was debited", "amount debited", "money is gone", "lost money", "i lost",
              "deducted", "పంపాను", "పంపేశాను", "కట్ అయ్యాయి", "కట్ అయింది", "డబ్బులు పోయాయి",
              "भेज दिए", "भेज दिया", "पैसे कट गए", "ट्रांसफर कर दिया", "पैसे चले गए"]
# Words typical of news or awareness forwards ("police bust digital-arrest gang"), not of the scam itself.
AWARENESS_WORDS = ["scam", "scams", "scammers", "beware", "awareness", "arrested", "gang", "busted", "alert:",
                   "మోసగాళ్లు", "జాగ్రత్త", "ठगों", "सावधान", "गिरोह"]
ONGOING_WORDS = ["on the call now", "still on the call", "on call now", "video call now", "they are on the line",
                 "on a video call", "calling me now", "ఇప్పుడు కాల్", "వీడియో కాల్‌లో ఉన్నాను", "अभी कॉल पर",
                 "वीडियो कॉल पर हूँ"]
CALL_VERBS = r"(?:call|contact|dial|ring|whatsapp|reach|phone|ఫోన్|కాల్|कॉल|फोन)"


def _asks_for_secret(text: str) -> bool:
    """True when the text asks someone to share an OTP/PIN/CVV (not 'do not share')."""
    for m in re.finditer(r"(share|send|tell|forward|provide|give|enter|batao|bataiye|cheppandi)\W+(?:\w+\W+){0,3}?"
                         r"(otp|o\.t\.p|pin(?!\s*code)|cvv|password)\b", text):
        before = text[max(0, m.start() - 15):m.start()]
        if not re.search(r"(not|never|don't|dont|do not|mat|kabhi|na)\W*$", before):
            if m.group(2) == "pin" and m.group(1) == "enter":
                continue  # "enter pin" is handled by the receive-money rule
            return True
    return any(w in text for w in ["ఓటీపీ చెప్పండి", "ఓటీపీ పంపండి", "ओटीपी बताएं", "ओटीपी बताइए", "ओटीपी भेजें"])


def _number_given_to_call(text: str, numbers: list[str]) -> bool:
    for num in numbers:
        tail = num[-10:]
        pattern = r"\D?".join(tail[:5]) + r"[\s-]?" + r"\D?".join(tail[5:])
        for m in re.finditer(pattern, text):
            if re.search(CALL_VERBS + r"\W+(?:\w+\W+){0,6}$", text[max(0, m.start() - 60):m.start()]):
                return True
    return False


# ----------------------------------------------------------------------------- rules

def apply_rules(text: str, ex: dict, domain_checks: dict, reputation: dict, media: list,
                forwarded: bool = False) -> tuple[list, list, list]:
    """Return (red_flags, genuine_signals, suggested_actions)."""
    t = (text or "").lower()
    flags, genuine, actions = [], [], []

    def flag(rule, severity, finding, fact, source):
        flags.append({"id": f"F{len(flags) + 1}", "rule": rule, "severity": severity, "finding": finding,
                      "fact": fact, "source": source})

    institution = _has(t, INSTITUTION)

    for link in ex["links"]:
        dc = domain_checks.get(link["host"], {})
        brand = dc.get("lookalike_of")
        if brand:
            flag("lookalike_domain", "high",
                 f"{link['host']} uses the name '{brand.upper()}' but is not an official {brand.upper()} website.",
                 f"Official {brand.upper()} websites: {', '.join(OFFICIAL_DOMAINS.get(brand, []))}.",
                 "Kavach official-domain list")
        age = dc.get("age_days")
        if isinstance(age, int) and age < 90:
            flag("new_domain", "high" if age < 30 else "medium",
                 f"{link['domain']} was registered only {age} days ago.",
                 "Scam websites are usually created days or weeks before they are used.", "RDAP registration record")
        if dc.get("ip_link"):
            flag("ip_link", "high", f"The link {link['url']} uses a raw IP address instead of a website name.",
                 "Banks and government websites always use a proper domain name.", "Kavach link check")
        tld = link["host"].rsplit(".", 1)[-1]
        if dc.get("cheap_tld") and institution:
            flag("cheap_tld", "medium", f"A message about {institution[0]} links to a cheap .{tld} domain.",
                 "Indian banks and government bodies use .com, .co.in, .bank.in or .gov.in domains.",
                 "Kavach link check")
        if dc.get("shortener"):
            flag("shortener", "medium", f"{link['host']} is a link shortener that hides the real address.",
                 "Short links in official messages from banks or government are rare; open them only after checking.",
                 "Kavach link check")
        if dc.get("protected_suffix"):
            genuine.append(f"{link['host']} ends in a protected suffix: {dc['protected_suffix']}.")
        elif dc.get("official_brand"):
            genuine.append(f"{link['host']} is an official {dc['official_brand'].upper()} domain.")
        if link["url"].lower().split("?")[0].endswith(".apk"):
            flag("apk_file", "critical", f"The link {link['url']} downloads an Android app file (.apk).",
                 "Banks and government departments do not send apps as .apk files; installing one can let "
                 "criminals read your OTPs and control your phone.", "Kavach rule")

    for item in media:
        name = (item.get("filename") or "").lower()
        if name.endswith(".apk") or "android.package-archive" in (item.get("mime_type") or ""):
            flag("apk_file", "critical", f"The file '{item.get('filename') or 'attachment'}' is an Android app (.apk).",
                 "Banks and government departments do not send apps as .apk files; installing one can let "
                 "criminals read your OTPs and control your phone.", "Kavach rule")

    if _asks_for_secret(t):
        flag("asks_for_otp", "critical", "The message asks for an OTP, PIN, CVV or password.",
             "No bank, government office or company will ever ask you to share an OTP, PIN, CVV or password.",
             "RBI and bank safety advisories")

    if _has(t, RECEIVE_WORDS) and _has(t, PIN_WORDS):
        flag("pin_to_receive", "high", "The message links receiving money with entering a UPI PIN or scanning a QR code.",
             "You never need to enter a UPI PIN or scan a QR code to receive money. Entering the PIN always "
             "sends money out of your account.", "NPCI UPI safety guidance")

    authority, coercion = _has(t, AUTHORITY), _has(t, COERCION)
    if authority and coercion:
        news_like = bool(_has(t, AWARENESS_WORDS))
        flag("digital_arrest", "low" if news_like else "critical",
             f"Mentions {authority[0]} together with {coercion[0]}, the pattern of a 'digital arrest' scam"
             + (" (this may be a news or awareness message about such scams)." if news_like else "."),
             "'Digital arrest' has no basis in Indian law. Police, CBI, ED and customs never arrest or question "
             "anyone over a video call, and never ask for money to prove innocence.", "MHA / I4C advisories")

    for upi in ex["upi_ids"]:
        if re.search(r"rbi|police|cbi|customs|govt|government|court|verify|verification|safe", upi.split("@")[0]):
            flag("authority_upi", "high", f"The UPI ID {upi} claims to belong to an authority or a 'verification' account.",
                 "The RBI, police and other government bodies never collect money from the public through UPI IDs.",
                 "RBI public advisories")

    if authority and not _has(t, AWARENESS_WORDS) and re.search(
            r"\b(pay|paid|transfer|transferred|deposit|send money|sent money)\b|పంప|చెల్లించ|भेज|ट्रांसफर", t):
        flag("authority_asks_money", "high", f"Someone claiming to be {authority[0]} is involved in a payment.",
             "Police, CBI, ED, customs and courts never ask anyone to pay money over a call or UPI to settle a case.",
             "MHA / I4C advisories")

    if _has(t, REMOTE_APPS):
        flag("remote_access_app", "critical", "The message asks to install or use a screen-sharing app.",
             "Screen-sharing apps let the other person see your OTPs and control your phone.", "Kavach rule")

    if institution and ex["mobile_numbers"] and _number_given_to_call(t, ex["mobile_numbers"]):
        flag("personal_number_for_institution", "high",
             f"A message about {institution[0]} asks you to contact a personal mobile number.",
             "Under TRAI rules, banks and financial firms must make service calls from 1600-series numbers "
             "(commercial banks since 1 January 2026). Official notices don't ask you to call a personal mobile.",
             "TRAI direction on the 1600 series")

    if _has(t, PRIZE_WORDS) and _has(t, FEE_WORDS):
        flag("fee_for_prize", "high", "The message promises a prize or lottery win but asks for a fee.",
             "Genuine prizes never require you to pay a fee, tax or GST first.", "Kavach rule")

    if _has(t, RETURNS_WORDS) and _has(t, INVEST_WORDS):
        flag("guaranteed_returns", "high", "The message promises guaranteed or very high investment returns.",
             "No genuine investment can guarantee returns. Check advisers on the SEBI website before investing.",
             "SEBI investor guidance")

    for ident, rep in reputation.items():
        n = rep.get("reports", 0)
        if n:
            flag("community_reports", "critical" if n >= 3 else "high",
                 f"{ident} has been reported {n} time(s) by Kavach users ({', '.join(rep.get('scam_types', []))}).",
                 "Kavach community reports from the last 90 days.", "Kavach community database")

    for num in ex["special_numbers"]:
        if num.startswith("1600"):
            genuine.append(f"{num} is in the 1600 series that TRAI assigned to banks and financial firms.")
    if ex.get("sms_header_type"):
        genuine.append(f"The SMS header {ex['sms_header']} is a registered {ex['sms_header_type']} sender ID "
                       "(TRAI header format since May 2025).")

    # Hints about the USER's situation; skipped for forwarded text, where "I sent" is the scammer talking.
    if not forwarded and _has(t, PAID_WORDS):
        actions.append("possible_money_loss: confirm the user (not the scammer) paid, then start_golden_hour")
    if not forwarded and _has(t, ONGOING_WORDS):
        actions.append("possible_ongoing_call: alert_family if the user is on the call now")
    return flags, genuine, actions


def verdict_floor(flags: list) -> str | None:
    if not flags:
        return None
    worst = max(flags, key=lambda f: SEVERITY_ORDER.index(f["severity"]))["severity"]
    return FLOOR_FOR_SEVERITY.get(worst)


def more_severe(a: str | None, b: str | None) -> str | None:
    if not a:
        return b
    if not b:
        return a
    return a if VERDICT_ORDER.index(a) >= VERDICT_ORDER.index(b) else b


# ----------------------------------------------------------------------------- main entry

def _parse_json_loose(raw: str):
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {"raw": raw[:2000]}


def build(text: str, media: list | None = None, user_phone: str = "", guardian_phones: list | None = None,
          forwarded: bool = False) -> dict:
    """Run every deterministic check and return the evidence sheet."""
    started = time.time()
    media = media or []
    image_findings, image_text = [], ""
    for item in media:
        if item.get("kind") in ("image", "document", "sticker") and item.get("s3_uri"):
            try:
                found = _parse_json_loose(analyze_media(item["s3_uri"], item.get("mime_type", "")))
            except Exception as exc:  # vision is best effort; rules still run on the text
                found = {"error": f"could not read file: {type(exc).__name__}"}
            image_findings.append(found)
            image_text += " " + str(found.get("visible_text", "")) + " " + " ".join(
                str(found.get(k, "")) for k in ("urls", "phone_numbers", "upi_ids"))

    full_text = f"{text}\n{image_text}"
    ex = extract(full_text)
    own = {kc.normalize_phone(p) for p in [user_phone, *(guardian_phones or [])] if p}
    ex["mobile_numbers"] = [n for n in ex["mobile_numbers"] if n not in own]

    def _domain(link):
        try:
            return link["host"], json.loads(check_domain(link["url"]))
        except Exception as exc:
            return link["host"], {"error": type(exc).__name__}

    identifiers = list(dict.fromkeys([l["domain"] for l in ex["links"]] + ex["mobile_numbers"] + ex["upi_ids"]))
    identifiers = identifiers[:MAX_IDENTIFIERS]

    def _rep(ident):
        try:
            return ident, json.loads(check_reputation(ident))
        except Exception as exc:  # e.g. config not deployed yet
            return ident, {"reports": 0, "error": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=8) as pool:
        domain_results = dict(pool.map(_domain, ex["links"]))
        reputation = dict(pool.map(_rep, identifiers))

    # Normalise check_domain output into simple booleans for the rules.
    for host, dc in domain_results.items():
        signals = " ".join(dc.get("signals", []))
        dc["cheap_tld"] = "Cheap top-level domain" in signals
        dc["shortener"] = "URL shortener" in signals
        dc["ip_link"] = "raw IP address" in signals

    flags, genuine, actions = apply_rules(full_text, ex, domain_results, reputation, media, forwarded)
    try:
        playbooks = json.loads(search_scam_playbooks(full_text)).get("matches", [])
        playbooks = [{"id": p["id"], "name": p["name"], "match_score": p["match_score"]} for p in playbooks[:2]]
    except Exception:
        playbooks = []

    return {
        "extracted": ex,
        "image_findings": image_findings,
        "domain_checks": {h: {k: v for k, v in dc.items() if k in ("registrable_domain", "signals", "age_days",
                                                                   "registered_on", "lookalike_of", "official_brand",
                                                                   "protected_suffix", "resolves", "error")}
                          for h, dc in domain_results.items()},
        "community_reports": {i: r for i, r in reputation.items() if r.get("reports")},
        "red_flags": flags,
        "genuine_signals": genuine,
        "matched_playbooks": playbooks,
        "verdict_floor": verdict_floor(flags),
        "suggested_actions": actions,
        "identifiers": identifiers,
        "seconds": round(time.time() - started, 1),
    }


# ----------------------------------------------------------------------------- reply grounding

def _numbers_near_call_words(text: str) -> set:
    """3-6 digit numbers presented as something to call (helplines, short codes), ignoring amounts."""
    found = set()
    for m in re.finditer(r"(?<![\d.,])(\d{3,6})(?![\d,])", text):
        if re.search(r"(₹|rs\.?|inr|rupees?)\s*$", text[max(0, m.start() - 8):m.start()], re.I):
            continue
        # English puts the verb first ("call 1930"); Telugu and Hindi put it after ("1930కి కాల్ చేయండి").
        if re.search(CALL_VERBS, text[max(0, m.start() - 35):m.start()], re.I) or \
                re.search(CALL_VERBS, text[m.end():m.end() + 20], re.I):
            found.add(m.group(1))
    return found


def contacts_in(text: str) -> tuple[set, set]:
    """Domains and phone numbers a reply mentions (normalised)."""
    text = text or ""
    domains = {_registrable(_host_of(_strip_url(m.group(0)))) for m in URL_RE.finditer(text)}
    numbers = {"+91" + re.sub(r"\D", "", m.group(1)) for m in MOBILE_RE.finditer(text)}
    numbers |= {re.sub(r"\D", "", m.group(1)) for m in SERIES_RE.finditer(text)}
    numbers |= _numbers_near_call_words(text)
    return {d for d in domains if d}, numbers


def ungrounded_contacts(reply: str, context_text: str) -> list[str]:
    """Websites or phone numbers in the reply that appear nowhere in the inputs, tool results or safe lists."""
    reply_domains, reply_numbers = contacts_in(reply)
    ctx_domains, ctx_numbers = contacts_in(context_text)
    ctx_digits = set(re.findall(r"\d{3,}", re.sub(r"(?<=\d)[\s-](?=\d)", "", context_text or "")))
    ctx_digits |= set(re.findall(r"\d{3,}", context_text or ""))
    ctx_numbers |= {n[-10:] for n in ctx_numbers} | ctx_digits
    allowed_domains = ctx_domains | SAFE_DOMAINS | OFFICIAL_REGISTRABLE
    bad = [d for d in sorted(reply_domains) if d not in allowed_domains]
    bad += [n for n in sorted(reply_numbers)
            if n not in SAFE_NUMBERS and n not in ctx_numbers and n[-10:] not in ctx_numbers]
    return bad


def identifiers_for_report(evidence: dict) -> list[str]:
    return [_normalize_identifier(i) for i in evidence.get("identifiers", [])]
