"""Swiggy sign-in callback (Lambda function URL).

The person sends LINK SWIGGY on WhatsApp, opens Swiggy's own sign-in page, logs in with phone and OTP, and
Swiggy redirects here with ?code=...&state=.... This exchanges the code for tokens (OAuth 2.1 + PKCE), stores
them for that person, and tells them on WhatsApp. The state is single-use and expires after 15 minutes.

Swiggy must approve this function's URL as a redirect URI first (see the SwiggyRedirectUri stack output).
"""
from __future__ import annotations

import html

import kavach_common as kc
import kavach_swiggy as ksw

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kavach</title></head><body style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:48px auto;padding:0 16px;color:#1c1917">
<h2 style="margin-bottom:8px">{title}</h2><p style="font-size:17px;line-height:1.5">{body}</p></body></html>"""


def _page(status: int, title: str, body: str) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
            "body": PAGE.format(title=html.escape(title), body=html.escape(body))}


def handler(event, _context):
    path = event.get("rawPath", "/")
    params = event.get("queryStringParameters") or {}
    if not path.rstrip("/").endswith("callback"):
        return _page(404, "Not found", "This address is only used by Swiggy's sign-in.")
    if params.get("error"):
        return _page(400, "Swiggy sign-in was cancelled", "Nothing was linked. You can send LINK SWIGGY on WhatsApp to try again.")
    code, state = params.get("code", ""), params.get("state", "")
    if not code or not state:
        return _page(400, "Something is missing", "Please start again by sending LINK SWIGGY on WhatsApp.")
    try:
        phone = ksw.finish_link(code, state)
    except ksw.NotLinked as exc:
        return _page(400, "This link has expired", f"{exc} Send LINK SWIGGY on WhatsApp to get a new one.")
    except Exception as exc:
        print(f"Swiggy link failed: {exc!r}")
        return _page(502, "Swiggy didn't confirm", "Please try again in a few minutes by sending LINK SWIGGY on WhatsApp.")
    try:
        kc.wa_text(phone, "✅ Your Swiggy account is linked. Tell me what you'd like to eat, for example "
                          "\"2 idli and a coffee\". I'll show you the order and total, and nothing is ordered until "
                          "you tap Place order (cash on delivery).")
    except Exception as exc:  # outside the 24-hour window; the page still confirms
        print(f"WhatsApp confirmation failed: {exc!r}")
    return _page(200, "Swiggy is linked ✅", "You can close this page and go back to WhatsApp.")
