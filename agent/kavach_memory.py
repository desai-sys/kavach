"""AgentCore Memory wiring (same pattern the AgentCore CLI generates).

`agentcore create ... --memory longAndShortTerm` creates a memory resource and passes
its id to the runtime in an env var named MEMORY_<NAME>_ID. We pick it up here.
"""
from __future__ import annotations

import os
import re

from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager


def _memory_id() -> str | None:
    explicit = os.getenv("KAVACH_MEMORY_ID")
    if explicit:
        return explicit
    for name, value in os.environ.items():
        if re.fullmatch(r"MEMORY_[A-Z0-9_]+_ID", name) and value:
            return value
    return None


def get_session_manager(session_id: str, actor_id: str) -> AgentCoreMemorySessionManager | None:
    memory_id = _memory_id()
    if not memory_id:
        print("No AgentCore Memory configured; running without memory")
        return None
    # Namespaces match the defaults the AgentCore CLI uses for long-term strategies.
    retrieval = {
        f"/users/{actor_id}/facts": RetrievalConfig(top_k=5, relevance_score=0.4),
        f"/users/{actor_id}/preferences": RetrievalConfig(top_k=3, relevance_score=0.5),
        f"/summaries/{actor_id}": RetrievalConfig(top_k=3, relevance_score=0.5),
    }
    return AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(memory_id=memory_id, session_id=session_id, actor_id=actor_id,
                              retrieval_config=retrieval),
        os.getenv("AWS_REGION", "ap-south-1"),
    )
