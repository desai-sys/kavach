# Kavach: a WhatsApp scam shield for Indian families

Kavach (कवच, "shield") lets anyone forward a suspicious message, link, screenshot, PDF or Telugu/Hindi
voice note on WhatsApp and get a clear verdict in their own language within a minute. An AI agent on
**Amazon Bedrock AgentCore** investigates with real tools. When someone is in danger, such as a live
"digital arrest" video call or money already sent, Kavach alerts the family on WhatsApp with
tap-to-confirm buttons, escalates if nobody answers, and runs a golden-hour response (1930 guidance plus
an emailed fraud report).

Built for the AWS Communication Developer Services (CDS) Agentic AI Partner Hackathon.

![Architecture](docs/architecture.png)

## AWS services used

| Service | What Kavach uses it for |
| --- | --- |
| **AWS End User Messaging Social (WhatsApp)** | Inbound messages and media via SNS; replies, interactive buttons, approved templates for family alerts and district scam warnings |
| **Amazon SES** | Family alert emails, golden-hour fraud report to the bank desk, Sunday family digest, optional forwarded-email checking (SES receiving) |
| **Amazon Bedrock AgentCore Runtime** | Hosts the Strands agent (`agent/`) |
| **AgentCore Memory** | Short-term conversation plus long-term facts per person (bank, past scams) |
| **AgentCore Browser** | Opens suspicious links in an isolated cloud browser and reports what the page asks for |
| **Amazon Bedrock (Amazon Nova 2 Lite, global inference profile from Mumbai)** | Agent reasoning, plus reading screenshots and PDF "notices" |
| **Amazon Transcribe** | Telugu (te-IN), Hindi (hi-IN) and English (en-IN) voice notes |
| **AWS Lambda, Amazon SNS, Amazon DynamoDB, Amazon S3** | Message handling, users/incidents/community reports, media (deleted after 7 days) |
| **Amazon EventBridge Scheduler** | 5-minute family escalation timers, 15-minute golden-hour check-ins, weekly digest |
| **AWS Systems Manager Parameter Store** | One shared config (`/kavach/config`) |

Region: **ap-south-1 (Mumbai)**. The optional email-checking stack runs in **ap-southeast-1 (Singapore)**,
because SES email receiving isn't offered in Mumbai.

## How Kavach avoids hallucinations: evidence first, model second, guard last

A wrong "this is safe" or an invented helpline number can cost a family their savings, so Kavach doesn't let
the model decide alone.

1. **Evidence first (code, `agent/evidence.py`).** Before the model runs, code reads any image or PDF once,
   extracts every link, phone number, UPI ID and amount with regular expressions, runs domain and
   community-report checks in parallel, and applies fixed red-flag rules. Each rule carries a verified fact,
   for example:
   - *Lookalike domain*: uses a bank's or brand's name but isn't on its official-domain list.
   - *Personal mobile for an institution*: under TRAI rules, banks must make service calls from 1600-series
     numbers (commercial banks since 1 January 2026).
   - *UPI PIN to receive money*: you never need a PIN or a QR scan to receive money.
   - *Digital arrest*: an authority plus coercion (video call, "don't tell anyone", money laundering).
   - Also: .apk files, OTP requests, screen-sharing apps, prize fees, guaranteed returns, "RBI" or "police"
     UPI IDs, and community reports.
   The rules produce a **verdict floor**, the mildest verdict the reply is allowed to give.
2. **Model second.** Amazon Nova 2 Lite gets the evidence sheet, investigates further (for example by opening
   links in AgentCore Browser), takes action, and writes the reply in the user's language.
3. **Guard last (`agent/guard.py`).** If the reply is milder than the floor, or mentions a website or phone
   number that appears nowhere in the user's message, the evidence or a tool result, Kavach asks the model to
   correct itself once. If it still fails, Kavach sends a fixed safe message or removes the unverified
   contact. The final verdict is always saved, even if the model forgot to record it.

Run the tests (no AWS account or internet needed): `pip install -r requirements-dev.txt && pytest`.

## Repository layout

```
agent/                    Kavach agent (Strands) for AgentCore Runtime
  main.py                 entrypoint: evidence -> agent -> guard, returns {"reply", "verdict", ...}
  evidence.py             extraction, parallel checks, fixed red-flag rules, verdict floor
  guard.py                verdict-floor and grounded-contact checks, correction round, fallback
  prompts.py              system prompt (evidence sheet, investigation steps, safety rules, reply format)
  tools/investigate.py    analyze_media, check_domain, inspect_link, check_reputation, search_scam_playbooks
  tools/act.py            alert_family, start_golden_hour, record_verdict
  playbooks.json          14 Indian scam playbooks with red flags and official facts
  kavach-agent-policy.json  extra IAM permissions for the runtime role
functions/                Lambda functions (Python 3.12, arm64)
  inbound/                WhatsApp in: onboarding, consent, buttons, media, voice, calls the agent
  escalation/             timer-driven family escalation and golden-hour check-in
  digest/                 Sunday family email
  community/              district scam-wave WhatsApp warning
  email_inbound/          optional: check forwarded emails (Singapore stack)
layers/common/kavach_common.py  shared WhatsApp/SES/DynamoDB helpers (Lambda layer + agent)
tests/                    offline tests for the rules, the guard and the agent flow
template.yaml             SAM stack for Mumbai
email-inbound.yaml        optional SAM stack for Singapore
scripts/                  install_agent.py, create_templates.sh, seed_demo.py, ask_agent.py, trigger_scam_wave.py
```

## Setup

Prerequisites: an AWS account, AWS CLI v2, AWS SAM CLI, Python 3.12, Node.js 20+, a Meta Business
portfolio and a phone number not yet registered on WhatsApp.

### 1. WhatsApp
1. In the **End User Messaging Social** console (Mumbai), link a WhatsApp Business Account and add your
   number. Note the **phone number ID** (`phone-number-id-...`) and the **WhatsApp Business Account ID**.
2. Submit the two templates: `./scripts/create_templates.sh <WABA_ID>` (or create them in the console
   from `scripts/whatsapp_templates/`).

### 2. Agent (AgentCore)
```bash
npm install -g @aws/agentcore@0.31.1   # 1.0.0 changed the create command
agentcore create --project-name KavachAgent --name Kavach --language Python \
  --framework Strands --model-provider Bedrock --memory longAndShortTerm --build CodeZip
python scripts/install_agent.py KavachAgent
cd KavachAgent && agentcore deploy && agentcore status   # copy the runtime ARN
```
Make sure `aws-targets.json` in the project points at `ap-south-1`.

### 3. Messaging backend (SAM)
```bash
sam build
sam deploy --guided --region ap-south-1 --capabilities CAPABILITY_NAMED_IAM
```
Parameters: `WhatsAppPhoneNumberId`, `AgentRuntimeArn`, `SenderEmail` and `BankFraudDeskEmail`
(both SES-verified). Then, in the End User Messaging Social console, set the WhatsApp Business Account's
**event destination** to the `InboundTopicArn` output.

### 4. Try it
```bash
python scripts/seed_demo.py --parent +9198XXXXXXXX --name "Lakshmi Amma" --language te \
  --district Kurnool --bank SBI --guardian "Ravi,+9198XXXXXXXX,ravi@example.com"
```
Then message the Kavach number from the parent's phone. Or test without WhatsApp:
`python scripts/ask_agent.py --arn <ARN> --phone +9198XXXXXXXX "Is this real? Your SBI account will be blocked, update KYC at sbi-kyc-update.xyz"`

### 5. Optional: forwarded-email checking
Verify a domain in SES **Singapore**, add an MX record to `inbound-smtp.ap-southeast-1.amazonaws.com`, then:
```bash
sam build -t email-inbound.yaml && sam deploy -t email-inbound.yaml --guided --region ap-southeast-1
aws ses set-active-receipt-rule-set --rule-set-name kavach-inbound --region ap-southeast-1
```

## Safety and privacy
- Consent is collected on WhatsApp before any check; `STOP` turns Kavach off.
- Media is deleted from S3 after 7 days. Community reports store the scammer's identifiers, never the
  reporter's number.
- Text inside screenshots and web pages is treated as untrusted evidence, never as instructions.
- Kavach never asks for OTPs, PINs or passwords, and does not fill or submit forms when it opens links.

## License
MIT. See [LICENSE](LICENSE).
