"""Shopping safely: turn a product (from a photo, an ad or a request) into links on official stores.

Kavach can't place Amazon or Flipkart orders: neither offers an ordering API to outside apps, and Amazon's
Product Advertising API 5.0 is deprecated. What it can do safely is identify the product and hand the person
a search link on the real store, so they buy in the official app instead of on a lookalike site from an ad.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

STORES = [
    ("Amazon", "https://www.amazon.in/s?k={q}"),
    ("Flipkart", "https://www.flipkart.com/search?q={q}"),
]


def product_query(product: dict | None) -> str:
    """A short search query from the vision model's product fields (brand, name, model)."""
    if not isinstance(product, dict):
        return ""
    words: list[str] = []
    for key in ("brand", "name", "model"):
        for w in str(product.get(key) or "").split():
            if w.lower() not in (x.lower() for x in words) and w.lower() not in ("null", "none", "unknown"):
                words.append(w)
    return re.sub(r"\s+", " ", " ".join(words)).strip()[:100]


def store_links(query: str) -> list[dict]:
    q = quote_plus(re.sub(r"[^\w\s.\-+/]", " ", query or "").strip())
    return [{"store": name, "url": pattern.format(q=q)} for name, pattern in STORES] if q else []


def lookup_from_findings(image_findings: list[dict]) -> dict | None:
    """The first product the vision model saw, with official store links."""
    for found in image_findings or []:
        product = found.get("product") if isinstance(found, dict) else None
        query = product_query(product)
        if query:
            return {
                "product": query,
                "price_shown_inr": product.get("price_shown_inr"),
                "original_price_inr": product.get("original_price_inr"),
                "seller_or_site_shown": product.get("seller_or_site_shown"),
                "is_shopping_ad": bool(found.get("is_shopping_ad")),
                "official_store_links": store_links(query),
                "note": "Kavach cannot place Amazon or Flipkart orders. Send these links so the person buys in "
                        "the official app; prices there are the real comparison.",
            }
    return None
