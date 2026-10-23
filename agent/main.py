"""Kavach agent entrypoint for Amazon Bedrock AgentCore Runtime.

Install into a project made by the AgentCore CLI with scripts/install_agent.py; it copies
this folder (plus layers/common/kavach_common.py) into app/Kavach/ and replaces the
generated main.py.

Invocation payload (sent by the inbound Lambda):
{
  "prompt": "...", "channel": "whatsapp" | "email", "message_id": "...",
  "media": [{"s3_uri": "s3://...", "mime_type": "image/jpeg", "kind": "image", ...}],
  "user": {"phone": "+91...", "name": "...", "language": "te", "district": "...", "bank": "...",
           "guardians": [{"name": "Ravi", "phone": "+91...", "email": "..."}]}
}
Response: {"reply": "<WhatsApp text>", "verdict": "...", "incident_id": "...", "actions": [...], "checks": {...},
           "business": "...", "buttons": [{"id": "BIZ|...", "title": "..."}], "buttons_text": "..."}

Flow (evidence first, model second, guard last):
  1. evidence.build()  - code reads files, extracts links/numbers/UPI IDs, runs checks and fixed rules,
                         and checks claims about a member business against that business's records
  2. the agent         - explains the evidence, investigates further, takes actions
  3. guard             - reply may not be milder than the rules, nor mention unverified contacts;
                         one correction round, then a deterministic fallback
  4. the verdict is always saved, even if the model forgot to call record_verdict
  5. member business   - buttons for the real action (sent by the inbound Lambda) and an anonymous
                         signal for the business's fraud report
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models.bedrock import BedrockModel

import evidence as ev
import guard
import kavach_business as kb
import kavach_common as kc
from kavach_context import start_request
from kavach_memory import get_session_manager
from prompts import build_system_prompt
from tools import ALL_TOOLS
from tools.act import save_verdict

# Amazon Nova 2 Lite through its global inference profile (serves Mumbai). Any Bedrock model
# with tool use works: set KAVACH_MODEL_ID in agentcore.json envVars, e.g.
# global.anthropic.claude-sonnet-4-6 if your account has Anthropic access.
MODEL_ID = os.getenv("KAVACH_MODEL_ID", "global.amazon.nova-2-lite-v1:0")

app = BedrockAgentCoreApp()
log = app.logger


def make_agent(user: dict, channel: str, session_manager):
    return Agent(
        # Near-greedy decoding keeps tool calls reliable.
        model=BedrockModel(model_id=MODEL_ID, max_tokens=2048, temperature=0.0),
        system_prompt=build_system_prompt(user, channel),
        tools=ALL_TOOLS,
        session_manager=session_manager,
        callback_handler=None,
    )


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    started = time.time()
    user = payload.get("user") or {}
    user["phone"] = kc.normalize_phone(user.get("phone", ""))
    req = start_request(user=user, message_id=payload.get("message_id"),
                        channel=payload.get("channel", "whatsapp"), media=payload.get("media") or [])
    prompt = payload.get("prompt") or "Hello"
    checks: dict = {"retried": False, "fallback_used": False, "removed_contacts": []}

    # 1. Evidence first.
    try:
        evidence = ev.build(prompt, req.media, user.get("phone", ""),
                            [g.get("phone", "") for g in user.get("guardians", [])],
                            forwarded="FORWARDED" in prompt)
    except Exception:
        log.exception("Evidence build failed; continuing with the model only")
        evidence = {"red_flags": [], "genuine_signals": [], "verdict_floor": None, "identifiers": [],
                    "suggested_actions": [], "matched_playbooks": []}
    req.evidence = evidence
    floor = evidence.get("verdict_floor")
    business = evidence.get("business_check")
    if business:  # tell the model which buttons the user will see after its reply
        evidence["buttons_after_reply"] = [b["title"] for b in kb.buttons_for(
            business["business_id"], floor or "NEED_MORE_INFO", req.language, is_customer=business["is_customer"])]
    prompt_with_sheet = f"{prompt}\n\nEVIDENCE SHEET (Kavach's own checks, run before you):\n{guard.sheet_for_model(evidence)}"

    digits = kc.phone_digits(user["phone"]) or "anonymous"
    session_id = (getattr(context, "session_id", None) or payload.get("session_id")
                  or f"kavach-session-{digits}-{datetime.now(kc.IST).strftime('%Y%m%d')}")
    session_manager = get_session_manager(session_id, f"user-{digits}")
    agent = make_agent(user, req.channel, session_manager)

    try:
        # 2. The model explains and acts.
        reply = _clean(str(agent(prompt_with_sheet)))

        # 3. Guard: verdict floor and grounded contacts, with one correction round.
        model_verdict = req.model_verdict or guard.verdict_from_reply(reply)
        # Judge what the user will SEE (the reply's first-line emoji), not only what was recorded.
        lenient = guard.too_lenient(guard.verdict_from_reply(reply) or model_verdict, floor)
        bad = ev.ungrounded_contacts(reply, guard.context_text(prompt_with_sheet, agent.messages))
        if lenient or bad:
            log.info("Guard correction: lenient=%s bad_contacts=%s", lenient, bad)
            checks["retried"] = True
            correction = guard.correction_prompt(evidence, lenient, bad)
            reply = _clean(str(agent(correction)))
            model_verdict = req.model_verdict or guard.verdict_from_reply(reply)
            if guard.too_lenient(guard.verdict_from_reply(reply) or model_verdict, floor):
                reply = guard.fallback_reply(req.language, floor)
                checks["fallback_used"] = True
            # The correction message names the bad contacts, so it must not count as "seen" context.
            context = guard.context_text(prompt_with_sheet, agent.messages).replace(correction, "")
            bad = ev.ungrounded_contacts(reply, context)
            if bad:
                reply = guard.scrub(reply, bad)
                checks["removed_contacts"] = bad
    except Exception as exc:
        log.exception("Agent failed")
        req.actions.append(f"error:{type(exc).__name__}")
        model_verdict = None
        reply = guard.fallback_reply(req.language, floor) if floor else kc.t("error", req.language)
    finally:
        close = getattr(session_manager, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                log.exception("Memory flush failed")

    # 4. Always save the final verdict (never milder than the rules).
    final = guard.final_verdict(model_verdict, floor)
    try:
        if req.verdict != final:
            flags = evidence.get("red_flags", [])
            playbooks = evidence.get("matched_playbooks") or []
            save_verdict(final,
                         scam_type=playbooks[0]["id"] if playbooks else "other",
                         risk_level=max((f["severity"] for f in flags), key=ev.SEVERITY_ORDER.index, default="low"),
                         summary=(flags[0]["finding"] if flags else prompt[:160]),
                         identifiers=ev.identifiers_for_report(evidence),
                         source="rules" if req.model_verdict else "kavach")
    except Exception:
        log.exception("Could not save the verdict")

    # 5. Member business: buttons for the real action, and an anonymous signal back to the business.
    buttons, buttons_text = [], None
    if business:
        buttons = kb.buttons_for(business["business_id"], final, req.language, req.incident_id,
                                 is_customer=business["is_customer"])
        buttons_text = kb.buttons_text(business["business_id"], req.language)
        scam_ids = ev.identifiers_for_report(evidence) if final in ("SCAM", "LIKELY_SCAM") else []
        try:
            if req.incident_id:
                kc.update_incident(req.incident_id, business_id=business["business_id"],
                                   business_claims=business["claims_found"], scam_identifiers=scam_ids)
            kb.record_signal(
                business["business_id"], "check", verdict=final, claims=business["claims_found"],
                contradictions=[c["finding"] for c in business["contradictions"]][:5],
                lookalike_domains=sorted({h for h, dc in evidence.get("domain_checks", {}).items()
                                          if dc.get("lookalike_of")}),
                scam_identifiers=scam_ids, is_customer=business["is_customer"],
                district=user.get("district", ""), language=req.language, channel=req.channel)
        except Exception:
            log.exception("Could not record the business signal")

    return {
        "reply": reply,
        "verdict": final,
        "model_verdict": req.model_verdict,
        "verdict_floor": floor,
        "red_flags": [f["rule"] for f in evidence.get("red_flags", [])],
        "business": business["business"] if business else None,
        "buttons": buttons,
        "buttons_text": buttons_text,
        "incident_id": req.incident_id,
        "actions": req.actions,
        "checks": {**checks, "evidence_seconds": evidence.get("seconds"),
                   "total_seconds": round(time.time() - started, 1)},
    }


def _clean(text: str) -> str:
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.S)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)  # WhatsApp has no headings
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)  # WhatsApp bold is *single* asterisks
    text = re.sub(r"__(.+?)__", r"_\1_", text)
    text = re.sub(r"\b[FG]\d{1,2}\b[:.]?\s?", "", text)  # never show evidence IDs
    return text.strip()


if __name__ == "__main__":
    app.run()
