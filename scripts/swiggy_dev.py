#!/usr/bin/env python3
"""Try Kavach's Swiggy food helper on YOUR OWN Swiggy account, in Swiggy's developer mode (localhost).

    pip install strands-agents mcp boto3
    python scripts/swiggy_dev.py            # add --relink to sign in again

1. Registers a developer client with Swiggy (redirect http://localhost:8765/callback, which Swiggy allows for
   development) and opens Swiggy's sign-in page. You log in with your phone number and OTP.
2. The tokens are saved in ~/.kavach/swiggy_dev.json on this computer only. They are never uploaded: the deployed
   WhatsApp bot uses its own sign-in, once Swiggy approves Kavach.
3. You chat with the same food agent Kavach uses (Amazon Nova 2 Lite on Bedrock, with your AWS credentials).

Orders are REAL and paid in cash on delivery (Swiggy caps them at ₹1000). Nothing is ordered until you type
"yes" at the confirmation.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "layers" / "common")]
os.environ.setdefault("AWS_REGION", "ap-south-1")

import kavach_swiggy as ksw  # noqa: E402

PORT = 8765
REDIRECT = f"http://localhost:{PORT}/callback"
TOKEN_FILE = Path.home() / ".kavach" / "swiggy_dev.json"


def sign_in() -> dict:
    client_id = ksw.register_client(REDIRECT)
    verifier, challenge = ksw.pkce_pair()
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            got.update(params)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Swiggy sign-in received. You can close this tab.</h2>".encode())

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("localhost", PORT), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    url = ksw.authorize_url(client_id, REDIRECT, challenge, state)
    print(f"Opening Swiggy sign-in. If the browser doesn't open, visit:\n{url}\n")
    webbrowser.open(url)
    deadline = time.time() + 180
    while "code" not in got and "error" not in got and time.time() < deadline:
        time.sleep(0.5)
    server.server_close()
    if got.get("state") != state or "code" not in got:
        sys.exit(f"Sign-in did not complete: {got.get('error') or 'timed out'}")
    tokens = ksw.exchange_code(got["code"], verifier, REDIRECT, client_id)
    saved = {"client_id": client_id, "access_token": tokens["access_token"],
             "refresh_token": tokens.get("refresh_token", ""),
             "expires_at": int(time.time()) + int(tokens.get("expires_in", 432000))}
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(saved), encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    print("Signed in to Swiggy.\n")
    return saved


def token(relink: bool) -> str:
    saved = None if relink or not TOKEN_FILE.exists() else json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    if not saved:
        saved = sign_in()
    if saved["expires_at"] - time.time() < ksw.REFRESH_MARGIN_S:
        tokens = ksw.refresh(saved["refresh_token"], saved.get("client_id", ""))
        saved.update(access_token=tokens["access_token"], refresh_token=tokens.get("refresh_token", ""),
                     expires_at=int(time.time()) + int(tokens.get("expires_in", 432000)))
        TOKEN_FILE.write_text(json.dumps(saved), encoding="utf-8")
    return saved["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relink", action="store_true", help="Sign in to Swiggy again")
    parser.add_argument("--language", default="en", choices=["en", "te", "hi"])
    args = parser.parse_args()

    import food  # needs strands-agents and mcp

    access = token(args.relink)
    print("Kavach food helper on Swiggy (developer mode). Orders are REAL, cash on delivery. Type 'quit' to stop.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text or text.lower() in ("quit", "exit"):
            break
        pending: dict = {}

        def on_confirm(address_id, total, summary):
            pending.update(token="local", address_id=address_id, total=total, summary=summary)
            return dict(pending)

        result = food.run_turn(food.client_for(access), text, args.language, on_confirm)
        print(f"\nKavach: {result['reply']}\n")
        if pending:
            total = f"₹{pending['total']:.0f}" if pending.get("total") is not None else "the total shown"
            answer = input(f"Place this order on Swiggy now? {pending['summary']} - {total}, cash on delivery. "
                           "Type yes to order: ").strip().lower()
            if answer == "yes":
                placed = food.place_order(food.client_for(access), pending["address_id"], pending.get("total"))
                print(f"\n{placed}\n")
            else:
                print("\nNot ordered.\n")


if __name__ == "__main__":
    main()
