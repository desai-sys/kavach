"""Test setup: put the agent and shared code on the path, and block all network and AWS access."""
import os
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "layers" / "common"), str(ROOT / "functions" / "inbound")]
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ.setdefault("AWS_REGION", "ap-south-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:ap-south-1:123456789012:runtime/test")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No DNS, no HTTP, no Kavach config: tests must not depend on the internet or an AWS account."""
    def no_dns(*_a, **_k):
        raise OSError("DNS disabled in tests")

    def no_http(*_a, **_k):
        raise OSError("HTTP disabled in tests")

    monkeypatch.setattr(socket, "gethostbyname", no_dns)
    monkeypatch.setattr(urllib.request, "urlopen", no_http)

    import kavach_common as kc

    def no_config():
        raise RuntimeError("no Kavach config in tests")

    monkeypatch.setattr(kc, "cfg", no_config)
    yield
