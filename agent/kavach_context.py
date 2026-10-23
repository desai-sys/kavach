"""Per-request context shared between the entrypoint and the tools.

Each AgentCore Runtime session runs in its own microVM, so a request-scoped
ContextVar is enough to give tools the current user without passing it through
the model.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

import kavach_common as kc


@dataclass
class Request:
    user: dict
    message_id: str | None = None
    channel: str = "whatsapp"
    media: list = field(default_factory=list)
    incident_id: str | None = None
    verdict: str | None = None          # last verdict saved to the incident
    model_verdict: str | None = None    # what the model itself passed to record_verdict
    reported: set = field(default_factory=set)  # identifiers already added to community reports
    evidence: dict | None = None
    actions: list = field(default_factory=list)
    ops_pending: dict | None = None     # ops mode: the one start/stop/reboot waiting for the owner's Yes
    list_message: dict | None = None    # a WhatsApp list (e.g. appointment times) to send after the reply
    food_pending: dict | None = None    # a Swiggy order waiting for the person's "Place order" tap
    direct_reply: str | None = None     # an everyday helper's answer, sent as is

    @property
    def phone(self) -> str:
        return kc.normalize_phone(self.user.get("phone", ""))

    @property
    def language(self) -> str:
        return self.user.get("language") or "en"

    def ensure_incident(self, kind: str, **fields) -> str:
        """Create one incident row per request, the first time a tool needs it."""
        if not self.incident_id:
            incident = kc.put_incident({
                "phone": self.phone, "name": self.user.get("name", ""), "type": kind,
                "district": self.user.get("district", ""), "message_id": self.message_id,
                "channel": self.channel, **fields,
            })
            self.incident_id = incident["incident_id"]
        elif fields:
            kc.update_incident(self.incident_id, **fields)
        return self.incident_id


_current: ContextVar[Request | None] = ContextVar("kavach_request", default=None)
_fallback: list[Request] = []  # tools may run in worker threads without the ContextVar copy


def start_request(**kwargs) -> Request:
    req = Request(**kwargs)
    _current.set(req)
    _fallback[:] = [req]
    return req


def current() -> Request:
    req = _current.get() or (_fallback[0] if _fallback else None)
    if req is None:
        raise RuntimeError("No active Kavach request")
    return req
