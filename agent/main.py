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
Response: {"reply": "<WhatsApp text>", "verdict": "...", "incident_id": "...", "actions": [...]}
"""
from __future__ import annotations

import os
import re
from datetime import datetime

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models.bedrock import BedrockModel

import kavach_common as kc
from kavach_context import start_request
from kavach_memory import get_session_manager
from prompts import build_system_prompt
from tools import ALL_TOOLS

MODEL_ID = os.getenv("KAVACH_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

app = BedrockAgentCoreApp()
log = app.logger


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    user = payload.get("user") or {}
    user["phone"] = kc.normalize_phone(user.get("phone", ""))
    req = start_request(user=user, message_id=payload.get("message_id"),
                        channel=payload.get("channel", "whatsapp"), media=payload.get("media") or [])

    digits = kc.phone_digits(user["phone"]) or "anonymous"
    session_id = (getattr(context, "session_id", None) or payload.get("session_id")
                  or f"kavach-session-{digits}-{datetime.now(kc.IST).strftime('%Y%m%d')}")
    actor_id = f"user-{digits}"
    session_manager = get_session_manager(session_id, actor_id)

    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID, max_tokens=2048, temperature=0.2),
        system_prompt=build_system_prompt(user, req.channel),
        tools=ALL_TOOLS,
        session_manager=session_manager,
        callback_handler=None,
    )
    try:
        result = agent(payload.get("prompt") or "Hello")
        reply = _clean(str(result))
    except Exception as exc:
        log.exception("Agent failed")
        reply = kc.t("error", req.language)
        req.actions.append(f"error:{type(exc).__name__}")
    finally:
        close = getattr(session_manager, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                log.exception("Memory flush failed")

    return {"reply": reply, "verdict": req.verdict, "incident_id": req.incident_id, "actions": req.actions}


def _clean(text: str) -> str:
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.S)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)  # WhatsApp has no headings
    return text.strip()


if __name__ == "__main__":
    app.run()
