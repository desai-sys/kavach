#!/usr/bin/env python3
"""Create a demo family and a few community scam reports.

Example:
  python scripts/seed_demo.py \
    --parent "+919800000001" --name "Lakshmi Amma" --language te --district Kurnool --bank SBI \
    --guardian "Ravi,+919800000002,ravi@example.com" \
    --guardian "Priya,+919800000003,priya@example.com" \
    --report "sbi-kyc-update.xyz:bank_kyc" --report "+919800000099:digital_arrest"

The parent is marked as already consented (status=active) so you can go straight to the demo, and gets
a demo customer record at each of the four fictional member businesses (Kalpavi Bank, Nidhira Health
Insurance, Dawaghar Pharmacy, Chamak Home Services). To (re)load only those records, for example to
refresh their dates before filming:
  python scripts/seed_demo.py --parent "+919800000001" --records-only
Uses your AWS CLI credentials and the /kavach/config parameter created by the SAM stack.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "layers" / "common"))
import kavach_business as kb  # noqa: E402
import kavach_common as kc  # noqa: E402

DEFAULT_REPORTS = ["sbi-kyc-update.xyz:bank_kyc", "refund.help.desk@ybl:upi_receive_money"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--parent", required=True, help="Protected person's WhatsApp number")
    p.add_argument("--name", default="", help="Protected person's name (required unless --records-only)")
    p.add_argument("--language", choices=["te", "hi", "en"], default="te")
    p.add_argument("--district", default="Kurnool")
    p.add_argument("--bank", default="SBI")
    p.add_argument("--email", default="", help="Optional email for the protected person")
    p.add_argument("--guardian", action="append", default=[], help='"Name,+91phone,email" (repeatable)')
    p.add_argument("--report", action="append", default=None,
                   help='"identifier:scam_type" community report to pre-load (repeatable)')
    p.add_argument("--no-business-records", action="store_true",
                   help="Skip the demo records at the four fictional member businesses")
    p.add_argument("--records-only", action="store_true",
                   help="Only (re)load the member-business records; leave the user and reports untouched")
    args = p.parse_args()
    if args.records_only:
        seed_business_records(args.parent, args.name or (kc.get_user(args.parent) or {}).get("name", ""))
        return
    if not args.name:
        p.error("--name is required")

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

    if not args.no_business_records:
        seed_business_records(args.parent, args.name)


def seed_business_records(phone: str, name: str) -> None:
    """Make the person a customer of all four fictional member businesses (bank, insurer, pharmacy, cleaning)."""
    for business_id, profile in kb.PROFILES.items():
        record = kb.demo_record(business_id, phone, name)
        kc.table("business_records_table").put_item(Item=kc.clean_for_dynamo(record))
        extra = f" (visit code {record['visit_code']})" if record.get("visit_code") else ""
        print(f"Saved demo customer record at {profile['name']}{extra}")


if __name__ == "__main__":
    main()
