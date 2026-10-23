#!/usr/bin/env python3
"""Send a district scam-wave warning now (for the demo).

  python scripts/trigger_scam_wave.py --district Kurnool \
      --summary "fake electricity disconnection messages asking you to call an officer"
"""
from __future__ import annotations

import argparse
import json

import boto3


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--district", required=True)
    p.add_argument("--scam-type", default="electricity_disconnection")
    p.add_argument("--summary", required=True)
    p.add_argument("--region", default="ap-south-1")
    args = p.parse_args()
    resp = boto3.client("lambda", region_name=args.region).invoke(
        FunctionName="kavach-community-alert",
        Payload=json.dumps({"district": args.district, "scam_type": args.scam_type, "summary": args.summary}).encode(),
    )
    print(resp["Payload"].read().decode())


if __name__ == "__main__":
    main()
