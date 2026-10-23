#!/usr/bin/env python3
"""Talk to the deployed Kavach agent directly (no WhatsApp needed for the question itself).

  python scripts/ask_agent.py --arn <runtime ARN> --phone +919800000001 \
      "Someone from CBI is on a video call saying my Aadhaar is used in money laundering"

The user profile is loaded from DynamoDB. Note: tools still act for real, so a critical
case WILL alert the guardians on WhatsApp and email.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "layers" / "common"))
import kavach_common as kc  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arn", required=True)
    p.add_argument("--phone", required=True)
    p.add_argument("--s3", help="Optional s3:// URI of an image/PDF to include")
    p.add_argument("--mime", default="image/jpeg")
    p.add_argument("text")
    args = p.parse_args()

    user = kc.get_user(args.phone) or {"phone": kc.normalize_phone(args.phone), "language": "en", "guardians": []}
    media = [{"s3_uri": args.s3, "mime_type": args.mime, "kind": "image"}] if args.s3 else []
    prompt = f"User's message:\n{args.text}"
    if args.s3:
        prompt += f"\n\nUser sent an image ({args.mime}) stored at {args.s3}."

    payload = {"prompt": prompt, "channel": "whatsapp", "message_id": f"cli-{int(time.time())}", "media": media,
               "user": {k: user.get(k) for k in ("phone", "name", "language", "district", "bank", "guardians", "email")}}
    client = boto3.client("bedrock-agentcore", region_name=kc.cfg()["region"],
                          config=Config(read_timeout=300, retries={"max_attempts": 1}))
    session = f"kavach-session-{kc.phone_digits(args.phone)}-{datetime.now(kc.IST).strftime('%Y%m%d')}"
    started = time.time()
    resp = client.invoke_agent_runtime(agentRuntimeArn=args.arn, runtimeSessionId=session,
                                       payload=json.dumps(payload).encode())
    body = resp["response"]
    raw = (body.read() if hasattr(body, "read") else b"".join(body)).decode()
    print(f"--- answered in {time.time() - started:.1f}s ---")
    try:
        data = json.loads(raw)
        print(data.get("reply", raw))
        print("\nverdict:", data.get("verdict"), "| model said:", data.get("model_verdict"),
              "| rules floor:", data.get("verdict_floor"), "| red flags:", data.get("red_flags"))
        print("actions:", data.get("actions"), "| checks:", data.get("checks"), "| incident:", data.get("incident_id"))
    except json.JSONDecodeError:
        print(raw)


if __name__ == "__main__":
    main()
