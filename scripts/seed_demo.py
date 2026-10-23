#!/usr/bin/env python3
"""Create a demo family and a few community scam reports.

Example:
  python scripts/seed_demo.py \
    --parent "+919800000001" --name "Lakshmi Amma" --language te --district Kurnool --bank SBI \
    --guardian "Ravi,+919800000002,ravi@example.com" \
    --guardian "Priya,+919800000003,priya@example.com" \
    --report "sbi-kyc-update.xyz:bank_kyc" --report "+919800000099:digital_arrest"

The parent is marked as already consented (status=active) so you can go straight to the demo.
Uses your AWS CLI credentials and the /kavach/config parameter created by the SAM stack.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "layers" / "common"))
import kavach_common as kc  # noqa: E402

DEFAULT_REPORTS = ["sbi-kyc-update.xyz:bank_kyc", "refund.help.desk@ybl:upi_receive_money"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--parent", required=True, help="Protected person's WhatsApp number")
    p.add_argument("--name", required=True)
    p.add_argument("--language", choices=["te", "hi", "en"], default="te")
    p.add_argument("--district", default="Kurnool")
    p.add_argument("--bank", default="SBI")
    p.add_argument("--email", default="", help="Optional email for the protected person")
    p.add_argument("--guardian", action="append", default=[], help='"Name,+91phone,email" (repeatable)')
    p.add_argument("--report", action="append", default=None,
                   help='"identifier:scam_type" community report to pre-load (repeatable)')
    args = p.parse_args()

    guardians = []
    for g in args.guardian:
        name, phone, *rest = [x.strip() for x in g.split(",")]
        guardians.append({"name": name, "phone": kc.normalize_phone(phone), "email": (rest[0] if rest else "").lower(),
                          "relation": "family"})

    kc.put_user({"phone": args.parent, "name": args.name, "language": args.language, "district": args.district,
                 "bank": args.bank, "email": args.email.lower(), "guardians": guardians, "status": "active",
                 "consent_at": kc.now_iso(), "created_at": kc.now_iso()})
    print(f"Saved {args.name} ({kc.normalize_phone(args.parent)}) with {len(guardians)} guardian(s)")

    for g in guardians:  # guardians can also message Kavach themselves
        if not kc.get_user(g["phone"]):
            kc.put_user({"phone": g["phone"], "name": g["name"], "language": "en", "status": "active",
                         "email": g["email"], "guardians": [], "district": "", "consent_at": kc.now_iso()})

    expires = int(time.time()) + 90 * 24 * 3600
    for item in (args.report if args.report is not None else DEFAULT_REPORTS):
        ident, _, scam_type = item.rpartition(":")
        ident = kc.normalize_phone(ident) if ident.startswith("+") else ident.lower()
        for _ in range(2):  # two prior reports each
            kc.table("reports_table").put_item(Item={
                "identifier": ident, "report_id": kc.new_id("seed"), "scam_type": scam_type,
                "district": args.district, "created_at": kc.now_iso(), "expires_at": expires})
        print(f"Seeded community reports for {ident} ({scam_type})")


if __name__ == "__main__":
    main()
