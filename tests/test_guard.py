"""The guard around the model: verdict floor, one correction round, fallback, grounding, saved verdict."""
import pytest

import guard
import kavach_common as kc
import main
from kavach_context import current

USER = {"phone": "+919800000001", "name": "Lakshmi Amma", "language": "te",
        "guardians": [{"name": "Ravi", "phone": "+919800000002"}]}
SCAM_TEXT = ("User's message:\nDear SBI customer, your YONO account will be blocked today. Update your PAN now: "
             "https://sbi-kyc-update.xyz/login")


class FakeAgent:
    """Returns scripted replies; optionally calls record_verdict like the real model would."""

    def __init__(self, replies, record=None):
        self.replies, self.record, self.messages, self.calls = list(replies), record, [], []

    def __call__(self, prompt):
        self.calls.append(prompt)
        self.messages.append({"role": "user", "content": [{"text": prompt}]})
        if self.record:
            current().model_verdict = self.record
        reply = self.replies.pop(0)
        self.messages.append({"role": "assistant", "content": [{"text": reply}]})
        return reply


@pytest.fixture
def saved(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "save_verdict", lambda verdict, **kw: calls.append((verdict, kw)))
    monkeypatch.setattr(main, "get_session_manager", lambda *_a: None)
    return calls


def run(monkeypatch, agent, text=SCAM_TEXT):
    monkeypatch.setattr(main, "make_agent", lambda *_a: agent)
    return main.invoke({"prompt": text, "user": dict(USER), "message_id": "m1"})


def test_lenient_reply_is_corrected_once(monkeypatch, saved):
    agent = FakeAgent(["✅ *ఇది నిజమైనదిగా కనిపిస్తోంది*", "🚨 *మోసం* • sbi-kyc-update.xyz SBI వెబ్‌సైట్ కాదు."])
    out = run(monkeypatch, agent)
    assert out["reply"].startswith("🚨")
    assert out["checks"]["retried"] and not out["checks"]["fallback_used"]
    assert "LIKELY_SCAM" in agent.calls[1] and "sbi-kyc-update.xyz" in agent.calls[1]
    assert out["verdict"] == "LIKELY_SCAM"


def test_fallback_when_model_still_says_safe(monkeypatch, saved):
    agent = FakeAgent(["✅ safe", "✅ still safe"])
    out = run(monkeypatch, agent)
    assert out["checks"]["fallback_used"]
    assert out["reply"] == guard.FALLBACK["scam"]["te"]
    assert saved and saved[0][0] == "LIKELY_SCAM"


def test_invented_contacts_are_removed(monkeypatch, saved):
    agent = FakeAgent(["🚨 *మోసం* SBI కస్టమర్ కేర్ 1800 1234 కి కాల్ చేయండి",
                       "🚨 *మోసం* SBI కస్టమర్ కేర్ 1800 1234 కి కాల్ చేయండి"])
    out = run(monkeypatch, agent)
    assert out["checks"]["retried"]
    assert "1800" not in out["reply"] and "1234" not in out["reply"]
    assert set(out["checks"]["removed_contacts"]) >= {"1800", "1234"}


def test_good_reply_passes_untouched(monkeypatch, saved):
    reply = "🚨 *మోసం*\n• sbi-kyc-update.xyz అధికారిక SBI సైట్ కాదు.\n1. లింక్ తెరవకండి. 2. 1930కి కాల్ చేయండి."
    out = run(monkeypatch, FakeAgent([reply], record="SCAM"))
    assert out["reply"] == reply
    assert not out["checks"]["retried"]
    assert out["verdict"] == "SCAM"


def test_verdict_saved_when_model_forgets(monkeypatch, saved):
    out = run(monkeypatch, FakeAgent(["🚨 *మోసం*"]))
    assert saved and saved[0][0] == "LIKELY_SCAM"
    assert saved[0][1]["source"] == "kavach"
    assert out["red_flags"] == ["lookalike_domain", "cheap_tld"]


def test_genuine_message_has_no_floor(monkeypatch, saved):
    text = "User's message:\nIs this the real India Post website? https://www.indiapost.gov.in"
    out = run(monkeypatch, FakeAgent(["✅ *ఇది అసలైన ఇండియా పోస్ట్ వెబ్‌సైట్ లాగా ఉంది*"], record="LIKELY_SAFE"), text)
    assert out["verdict_floor"] is None and out["verdict"] == "LIKELY_SAFE"
    assert not out["checks"]["retried"]


def test_model_error_still_answers_safely(monkeypatch, saved):
    class Broken(FakeAgent):
        def __call__(self, prompt):
            raise RuntimeError("model down")

    out = run(monkeypatch, Broken([]))
    assert out["reply"] == guard.FALLBACK["scam"]["te"]


def test_evidence_ids_never_shown():
    assert main._clean("🚨 *SCAM* F1: lookalike. G1 official") == "🚨 *SCAM* lookalike. official"
    assert main._clean("🚨 **SCAM**") == "🚨 *SCAM*"


def test_kavach_common_is_offline():
    with pytest.raises(RuntimeError):
        kc.cfg()
