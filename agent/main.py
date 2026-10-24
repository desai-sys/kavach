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

{"mode": "ops"} payloads (owner-only "aws ..." messages) go to ops.py instead.
"""
from __future__ import annotations

import os
import json
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
import ops
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
    if payload.get("mode") == "ops":  # owner-only AWS console; separate prompt, tools and memory
        return ops.invoke(payload, context)
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
    prompt_with_sheet = (f"{prompt}\n\nEVIDENCE SHEET (Kavach's own checks, run before you):\n"
                         f"{guard.sheet_for_model(evidence)}\n\n{guard.language_line(req.language)}")

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

        # 3a. Language: the person's chosen language wins over memory and over the language of the message.
        if guard.wrong_language(reply, req.language):
            log.info("Guard correction: reply not in %s", req.language)
            checks["language_fixed"] = True
            fixed = _clean(str(agent(guard.language_correction(req.language))))
            if not guard.wrong_language(fixed, req.language):
                reply = fixed
            elif floor:
                reply = guard.fallback_reply(req.language, floor)
                checks["fallback_used"] = True
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

    # 3b. A person asking for a doctor gets the list of times even if the model forgot to look them up.
    risky = (req.model_verdict or "") in ("SCAM", "LIKELY_SCAM", "SUSPICIOUS")
    if evidence.get("doctor_request") and not floor and not risky and not req.list_message and not req.buttons:
        try:
            from tools.everyday import offer_slots
            offer_slots(evidence["doctor_request"]["concern"])
        except Exception:
            log.exception("Could not offer appointment times")

    # 3c. Buttons and lists carry their own instructions in the person's language; "tap the button below"
    #     from the model is removed, so nobody looks for a button that never comes.
    reply = guard.strip_button_talk(reply)

    # 4. Always save the final verdict (never milder than the rules), unless this was only an everyday
    #    request (a product link, an appointment) with nothing suspicious in it.
    final = guard.final_verdict(model_verdict, floor)
    errand_only = (not floor and not req.model_verdict and any(a.startswith("errand_") for a in req.actions))
    try:
        if req.verdict != final and not errand_only:
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

    # 4b. Family alert in code: if the person's own words show a scam happening to them now and the model
    #     didn't alert the family (or only said it did), Kavach does it, with the 5-minute escalation.
    if not any(a in req.actions for a in ("family_alerted", "golden_hour_started")):
        why = guard.danger_now(prompt, evidence, final, reply, user.get("guardians") or [],
                               forwarded="FORWARDED" in prompt)
        if why:
            reply = _alert_family_now(req, why, reply)

    # 5. Member business: buttons for the real action, and an anonymous signal back to the business.
    buttons, buttons_text = list(req.buttons or []), req.buttons_text
    if business and not req.list_message and not buttons:
        buttons = kb.buttons_for(business["business_id"], final, req.language, req.incident_id,
                                 is_customer=business["is_customer"])
        buttons_text = kb.buttons_text(business["business_id"], req.language)
    if business:
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
        "list": req.list_message,
        "incident_id": req.incident_id,
        "actions": req.actions,
        "checks": {**checks, "evidence_seconds": evidence.get("seconds"),
                   "total_seconds": round(time.time() - started, 1)},
    }


def _alert_family_now(req, why: str, reply: str) -> str:
    """Run the alert_family tool from code and add one line to the reply saying who was told."""
    names = [g.get("name") or g.get("phone") for g in req.user.get("guardians") or []]
    if not names:
        return reply + "\n\n" + kc.t("no_family", req.language)
    try:
        from tools.act import alert_family
        out = json.loads(alert_family(severity="critical", what_is_happening=why,
                                      what_family_should_do="Call them now and ask them to hang up. Make sure "
                                                            "they don't pay or share any OTP."))
        req.actions.append("family_alerted_by_code")
    except Exception:
        log.exception("Family alert from code failed")
        return reply
    reached, missed = out.get("alerted_names") or [], out.get("not_reached_on_whatsapp") or []
    lines = []
    if reached and not any(n.lower() in reply.lower() for n in reached):
        lines.append(kc.t("family_alerted", req.language).format(names=", ".join(reached)))
    if missed:  # never let her think someone was told when WhatsApp refused it
        lines.append(kc.t("family_not_reached", req.language).format(names=", ".join(missed)))
    return reply + ("\n\n" + "\n".join(lines) if lines else "")


def _clean(text: str) -> str:
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.S)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)  # WhatsApp has no headings
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)  # WhatsApp bold is *single* asterisks
    text = re.sub(r"__(.+?)__", r"_\1_", text)
    text = re.sub(r"\b[FG]\d{1,2}\b[:.]?\s?", "", text)  # never show evidence IDs
    return text.strip()


if __name__ == "__main__":
    app.run()
