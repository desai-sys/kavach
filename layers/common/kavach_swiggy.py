"""Swiggy account linking and order confirmations for Kavach (no AI here).

Kavach orders food through Swiggy's official MCP server (https://mcp.swiggy.com/food), as the person's own
Swiggy account. This module holds the parts that must not depend on a model:

  * linking: OAuth 2.1 + PKCE, as Swiggy documents it. The person taps a swiggy.com link, signs in with phone
    and OTP, and Swiggy redirects to Kavach's callback (functions/swiggy_link). Tokens are stored per person in
    the kavach-linked-accounts table and refreshed before they expire (refresh tokens rotate).
  * confirmations: the food agent can only REQUEST an order. Kavach shows "Place order" / "Cancel", and the
    order is placed (cash on delivery, under Swiggy's ₹1000 cap) only after that tap. Requests are single-use
    and expire after 10 minutes.

Switched off until Swiggy approves Kavach's redirect URI (config swiggy_enabled). Developers can try the same
flow on their own account in Swiggy's developer mode with scripts/swiggy_dev.py.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from botocore.exceptions import ClientError

import kavach_common as kc

BASE = "https://mcp.swiggy.com"
FOOD_MCP_URL = f"{BASE}/food"
AUTHORIZE_URL = f"{BASE}/auth/authorize"
TOKEN_URL = f"{BASE}/auth/token"
REGISTER_URL = f"{BASE}/auth/register"
SCOPE = "mcp:tools"
CART_CAP_INR = 1000
CONFIRM_MINUTES = 10
REFRESH_MARGIN_S = 24 * 3600


class NotLinked(Exception):
    """The person hasn't linked a Swiggy account (or Swiggy revoked it)."""


def enabled() -> bool:
    try:
        return str(kc.cfg().get("swiggy_enabled", "false")).lower() == "true"
    except Exception:
        return False


# ----------------------------------------------------------------------------- HTTP and PKCE

def _post_json(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors="replace")
        raise RuntimeError(f"Swiggy {url.rsplit('/', 1)[-1]} failed: HTTP {exc.code} {detail}") from None


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def register_client(redirect_uri: str) -> str:
    """Dynamic Client Registration (RFC 7591). Swiggy issues a client_id; no secret for public clients."""
    resp = _post_json(REGISTER_URL, {"client_name": "Kavach", "redirect_uris": [redirect_uri],
                                     "grant_types": ["authorization_code", "refresh_token"],
                                     "response_types": ["code"], "token_endpoint_auth_method": "none",
                                     "scope": SCOPE})
    if not resp.get("client_id"):
        raise RuntimeError(f"Swiggy registration returned no client_id: {str(resp)[:200]}")
    return resp["client_id"]


def authorize_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "code_challenge": challenge,
        "code_challenge_method": "S256", "state": state, "scope": SCOPE})


def exchange_code(code: str, verifier: str, redirect_uri: str, client_id: str) -> dict:
    return _post_json(TOKEN_URL, {"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                  "redirect_uri": redirect_uri, "client_id": client_id})


def refresh(refresh_token: str, client_id: str = "") -> dict:
    body = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    if client_id:
        body["client_id"] = client_id
    return _post_json(TOKEN_URL, body)


# ----------------------------------------------------------------------------- linking through WhatsApp

def _accounts():
    return kc.table("linked_accounts_table")


def _redirect_uri() -> str:
    uri = kc.cfg().get("swiggy_redirect_uri", "")
    if not uri.startswith("https://"):
        raise RuntimeError("swiggy_redirect_uri is not configured")
    return uri


def _client_id(redirect_uri: str) -> str:
    key = {"phone": "#client", "provider": f"swiggy|{redirect_uri}"}
    item = _accounts().get_item(Key=key).get("Item")
    if item:
        return item["client_id"]
    client_id = register_client(redirect_uri)
    _accounts().put_item(Item={**key, "client_id": client_id, "created_at": kc.now_iso()})
    return client_id


def start_link(phone: str) -> str:
    """A swiggy.com sign-in link for this person. The state ties Swiggy's redirect back to their number."""
    redirect_uri = _redirect_uri()
    client_id = _client_id(redirect_uri)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    kc.table("dedupe_table").put_item(Item={"message_id": f"swl-{state}", "kind": "swiggy_link",
                                            "phone": kc.normalize_phone(phone), "verifier": verifier,
                                            "expires_at": int(time.time()) + 15 * 60})
    return authorize_url(client_id, redirect_uri, challenge, state)


def finish_link(code: str, state: str) -> str:
    """Swiggy redirected back with a code: exchange it and store the tokens. Returns the person's phone."""
    try:
        item = kc.table("dedupe_table").delete_item(
            Key={"message_id": f"swl-{state}"}, ConditionExpression="attribute_exists(message_id)",
            ReturnValues="ALL_OLD").get("Attributes")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise NotLinked("This sign-in link was already used or has expired.") from None
        raise
    item = kc.to_jsonable(item or {})
    if not item or int(item.get("expires_at", 0)) < time.time():
        raise NotLinked("This sign-in link has expired.")
    redirect_uri = _redirect_uri()
    client_id = _client_id(redirect_uri)
    tokens = exchange_code(code, item["verifier"], redirect_uri, client_id)
    save_tokens(item["phone"], tokens, client_id)
    return item["phone"]


def save_tokens(phone: str, tokens: dict, client_id: str = "") -> None:
    if not tokens.get("access_token"):
        raise RuntimeError("Swiggy returned no access token")
    _accounts().put_item(Item=kc.clean_for_dynamo({
        "phone": kc.normalize_phone(phone), "provider": "swiggy", "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""), "client_id": client_id,
        "expires_at": int(time.time()) + int(tokens.get("expires_in", 432000)), "updated_at": kc.now_iso()}))


def is_linked(phone: str) -> bool:
    try:
        return bool(_accounts().get_item(Key={"phone": kc.normalize_phone(phone), "provider": "swiggy"}).get("Item"))
    except Exception:
        return False


def access_token(phone: str) -> str:
    """A valid access token for this person, refreshed (and rotated) when it is close to expiry."""
    key = {"phone": kc.normalize_phone(phone), "provider": "swiggy"}
    item = _accounts().get_item(Key=key).get("Item")
    if not item:
        raise NotLinked("No Swiggy account linked.")
    item = kc.to_jsonable(item)
    if int(item.get("expires_at", 0)) - time.time() > REFRESH_MARGIN_S:
        return item["access_token"]
    try:
        tokens = refresh(item.get("refresh_token", ""), item.get("client_id", ""))
    except RuntimeError as exc:
        if "invalid_grant" in str(exc) or "HTTP 400" in str(exc) or "HTTP 401" in str(exc):
            _accounts().delete_item(Key=key)
            raise NotLinked("Swiggy sign-in expired; please link again.") from None
        raise
    save_tokens(phone, tokens, item.get("client_id", ""))
    return tokens["access_token"]


def unlink(phone: str) -> None:
    _accounts().delete_item(Key={"phone": kc.normalize_phone(phone), "provider": "swiggy"})


# ----------------------------------------------------------------------------- confirm, then order

def create_pending(phone: str, address_id: str, total: float | None, summary: str) -> dict:
    token = secrets.token_hex(8)
    kc.table("dedupe_table").put_item(Item=kc.clean_for_dynamo({
        "message_id": f"food-{token}", "kind": "food_pending", "phone": kc.normalize_phone(phone),
        "address_id": address_id, "total": float(total) if total is not None else None, "summary": summary[:300],
        "expires_at": int(time.time()) + CONFIRM_MINUTES * 60}))
    return {"token": token, "total": total, "summary": summary}


def take_pending(phone: str, token: str) -> dict:
    """Single use: the request is deleted before the order is placed. Raises NotLinked if gone or expired."""
    try:
        item = kc.table("dedupe_table").delete_item(
            Key={"message_id": f"food-{token}"},
            ConditionExpression="attribute_exists(message_id) AND #k = :kind AND #p = :phone",
            ExpressionAttributeNames={"#k": "kind", "#p": "phone"},
            ExpressionAttributeValues={":kind": "food_pending", ":phone": kc.normalize_phone(phone)},
            ReturnValues="ALL_OLD").get("Attributes")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise NotLinked("This order request was already handled or has expired.") from None
        raise
    item = kc.to_jsonable(item or {})
    if not item or int(item.get("expires_at", 0)) < time.time():
        raise NotLinked("This order request has expired.")
    return item


BUTTONS = {
    "place": {"en": "Place order", "te": "ఆర్డర్ చేయండి", "hi": "ऑर्डर करें"},
    "cancel": {"en": "Cancel", "te": "వద్దు", "hi": "रद्द करें"},
    "question": {
        "en": "Order on Swiggy: {summary}{total}. You pay cash on delivery. Nothing is ordered until you tap Place order.",
        "te": "Swiggyలో ఆర్డర్: {summary}{total}. డెలివరీ సమయంలో నగదు చెల్లించాలి. 'ఆర్డర్ చేయండి' నొక్కే వరకు ఏమీ ఆర్డర్ కాదు.",
        "hi": "Swiggy पर ऑर्डर: {summary}{total}। डिलीवरी पर नकद भुगतान। 'ऑर्डर करें' दबाने तक कुछ ऑर्डर नहीं होगा।",
    },
}


def confirm_prompt(pending: dict, lang: str) -> tuple[str, list[dict]]:
    lang = lang if lang in ("en", "te", "hi") else "en"
    total = f" (₹{pending['total']:.0f})" if pending.get("total") is not None else ""
    text = BUTTONS["question"][lang].format(summary=pending["summary"], total=total)
    return text, [{"id": f"FOOD|yes|{pending['token']}", "title": BUTTONS["place"][lang]},
                  {"id": f"FOOD|no|{pending['token']}", "title": BUTTONS["cancel"][lang]}]
