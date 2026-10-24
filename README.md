# Kavach: a WhatsApp scam shield for Indian families

Kavach (कवच, "shield") lets anyone forward a suspicious message, link, screenshot, PDF or Telugu/Hindi
voice note on WhatsApp and get a clear verdict in their own language within a minute. An AI agent on
**Amazon Bedrock AgentCore** investigates with real tools. When someone is in danger, such as a live
"digital arrest" video call or money already sent, Kavach alerts the family on WhatsApp with
tap-to-confirm buttons, escalates if nobody answers, and runs a golden-hour response (1930 guidance plus
an emailed fraud report).

Businesses can join Kavach as members: a bank, insurer, pharmacy, clinic or home-services company shares its
official channels, its rules and a masked view of each customer's record. When a message claims to come
from a member, Kavach checks the claim against the customer's real record ("your policy lapses today" vs
"active until March 2027") and offers one-tap buttons for the real action.

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
| **AWS Lambda, Amazon SNS, Amazon DynamoDB, Amazon S3** | Message handling; users, incidents, community reports, member-business records and signals; media (deleted after 7 days) |
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

## Kavach for businesses: check with the business, then do the real thing

Most scams impersonate a business the victim really uses: their bank, their health insurer, their pharmacy,
the cleaning service they booked. Kavach lets any such business join as a **member** and run Kavach on its
own WhatsApp number for its own customers. A member shares four things (`layers/common/businesses.json`):

| What the business shares | What Kavach does with it |
| --- | --- |
| Official channels: websites, SMS sender IDs, how it takes payments | Flags lookalike sites, unofficial UPI IDs and links; recognises its genuine SMS headers |
| Its rules: what it never does ("never takes an advance", "never cancels a policy over WhatsApp") | Fixed red flags when a message breaks them |
| A masked slice of each customer's record (status fields plus a short summary in Telugu, Hindi and English) | Checks the message's claims against the customer's real record: "your policy will lapse today" vs "active until 31 Mar 2027, nothing due" |
| A few safe actions | Buttons after the verdict: get the real details, request a call back, report the scam, reserve a refill, show a booking's visit code |

Every one of these checks is plain code over records (`kavach_business.verify`), so it adds to the verdict
floor and can't be hallucinated. Button taps go straight to the inbound Lambda, not through the model, and
records are always looked up by the sender's own WhatsApp number. Each check also writes an anonymous
signal (claims, lookalike domains, scammer identifiers, district; no customer phone numbers) to
`kavach-business-signals` for the business's fraud-intelligence report.

**How a customer's record reaches Kavach.** The customer opts in with the business (in its app, at its counter,
or while renewing), and the business links a masked record to the mobile number registered with it. That is the
same number as the customer's WhatsApp, which WhatsApp verified when they installed it, so only a message from
their own phone can read their record, much like Indian banks run WhatsApp banking for existing customers. The
customer sees every linked service in **Settings > Linked services** ("Linked 3 Oct via the Kalpavi Bank app;
Kavach can see: account status, KYC date, last 2 transactions, masked") and can unlink it there. A business can
also run Kavach in its own AWS account, so its records never leave it.

The demo ships with five **fictional** members, so no real company is impersonated:

| Business | Kind | A scam Kavach catches with its records |
| --- | --- | --- |
| Kalpavi Bank | bank | "Account blocked, KYC expired": records show the account is active and KYC valid until 2028 |
| Nidhira Health Insurance | insurer | "Policy lapses today, pay ₹14,200": the amount is real, but it's not due until 15 Mar 2027 |
| Dawaghar Pharmacy | pharmacy | "Order on hold, pay ₹1,250": nothing is out for delivery; the next refill is ₹412, paid on delivery |
| Chamak Home Services | home services | "Pay ₹999 advance or your slot is cancelled": the booking is confirmed and Chamak never takes advances |
| Dhanvi Family Clinic | clinic | "Pay ₹500 advance to confirm your appointment": the visit is booked and fees are paid at the reception |

## Everyday help, done safely

Kavach also helps with a few everyday jobs, always through the official channel, and never spending money or
booking anything on the AI's word alone: the person's own tap does that.

| Ask | What Kavach does | What's real |
| --- | --- | --- |
| A photo or ad of a product ("is this a good deal?", "buy this") | Reads the product from the picture and replies with search links on the real amazon.in and flipkart.com; flags 70%+ discounts from sellers it can't verify | Links only: neither store offers an ordering API to outside apps, and Amazon's Product Advertising API 5.0 is deprecated |
| "I need a doctor for my knee pain" | Picks the right doctor at the member clinic, sends a WhatsApp list of free times; the tap books it (a conditional write, so nobody gets the same slot), confirms on WhatsApp, emails the family through SES, and EventBridge sends a reminder with "I'm on my way" / "Cancel visit" | Fully working with the fictional Dhanvi Family Clinic; a real clinic joins as a member |

## Settings any time, without commands

Elderly users shouldn't have to remember `GUARDIAN Ravi +91…`. `MENU` (or `hi`, `మెనూ`, `मेनू`) opens a WhatsApp list:
language, family contacts, add a family member, linked services, district, pause or turn on, and examples. Short
requests in Telugu, Hindi or English work too ("change language", "భాష", "English", "STOP", "add Priya 98765
43210"), a contact card shared from the phone book adds a family member, and changing the language never asks for
consent again. Longer requests in the person's own words go to the agent, which opens the right menu
(`open_settings`) or offers a **Yes, add** button (`add_family_contact`); nothing changes until the person taps.
Forwarded messages are never treated as settings. All of this is plain code in `layers/common/kavach_settings.py`.

Kavach's replies never tell people to tap a button that isn't there: the guard removes "tap the button below"
lines (buttons and lists arrive with their own instructions), and a request for a doctor always gets the list of
times (or a **Call me back** button when nothing is free), even if the model forgets to look them up.

## Ops mode: run the deployment from WhatsApp (owner only)

The partner running Kavach can manage it, and their AWS account, from the same WhatsApp number. Messages that
start with `aws` (or `ops`), typed by a number listed in the `OpsOwnerPhones` parameter, go to a separate ops
agent with its own prompt, tools and memory. Everything else, including anything forwarded, still gets the
scam check.

```
aws are my WhatsApp templates approved?        -> template status, SES sandbox or not, Lambda errors, today's checks
aws how much have I spent this month?          -> Cost Explorer, top services
aws which instances are running?               -> EC2 across the regions in OpsRegions
aws stop dev-server                            -> "Stop dev-server (i-0abc...) in ap-south-1?"  [Yes, do it] [Cancel]
```

Safety: the ops agent only has view-only permissions, and calls that could return secrets or stored data are
refused in code. It can only *request* a start, stop or reboot; the inbound Lambda runs it when the owner taps
**Yes**, and each request is single-use and expires after 10 minutes. No Kavach role can terminate or delete
anything or change security groups or IAM, so a misread message or a hijacked chat can't do lasting damage.

## Repository layout

```
agent/                    Kavach agent (Strands) for AgentCore Runtime
  main.py                 entrypoint: evidence -> agent -> guard, returns {"reply", "verdict", ...}
  evidence.py             extraction, parallel checks, fixed red-flag rules, verdict floor
  guard.py                verdict-floor and grounded-contact checks, correction round, fallback
  prompts.py              system prompt (evidence sheet, investigation steps, safety rules, reply format)
  tools/investigate.py    analyze_media, check_domain, inspect_link, check_reputation, search_scam_playbooks
  tools/business.py       check_business_records, business_action (member businesses)
  tools/everyday.py       find_product_online, find_appointment_slots, my_appointments, cancel_appointment
  tools/settings.py       open_settings, add_family_contact (show a menu or a Yes button; the tap changes it)
  shopping.py             official store links from a product in a photo or ad
  ops.py, tools/ops.py    owner-only ops mode: list_instances, aws_spend_this_month, kavach_status, aws_read,
                          request_instance_action
  tools/act.py            alert_family, start_golden_hour, record_verdict
  playbooks.json          14 Indian scam playbooks with red flags and official facts
  kavach-agent-policy.json  extra IAM permissions for the runtime role
functions/                Lambda functions (Python 3.12, arm64)
  inbound/                WhatsApp in: onboarding, consent, settings, buttons, media, voice, calls the agent
  escalation/             timer-driven family escalation and golden-hour check-in
  digest/                 Sunday family email
  community/              district scam-wave WhatsApp warning
  email_inbound/          optional: check forwarded emails (Singapore stack)
layers/common/            shared by the Lambda layer and the agent
  kavach_common.py        WhatsApp/SES/DynamoDB helpers
  kavach_business.py      member businesses: claims vs records, buttons, official actions, signals
  businesses.json         the five fictional demo members and their demo customer records
  kavach_ops.py           ops mode: owner check, Yes/Cancel requests, runs the confirmed EC2 action
  kavach_clinic.py        clinic slots, booking (no double booking), confirmations, reminders
  kavach_settings.py      settings menu, language, family contacts, pause, linked services (plain code)
tests/                    offline tests for the rules, the guard and the agent flow
template.yaml             SAM stack for Mumbai
email-inbound.yaml        optional SAM stack for Singapore
scripts/                  install_agent.py, create_templates.sh, seed_demo.py, ask_agent.py, trigger_scam_wave.py
docs/                     architecture diagram (draw_architecture.py redraws it), demo kit, website
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
(both SES-verified). Optional: `OpsOwnerPhones` (your number, to turn on ops mode) and `OpsRegions`. Then, in the End User Messaging Social console, set the WhatsApp Business Account's
**event destination** to the `InboundTopicArn` output.

### 4. Try it
```bash
python scripts/seed_demo.py --parent +9198XXXXXXXX --name "Lakshmi Amma" --language te \
  --district Kurnool --bank SBI --guardian "Ravi,+9198XXXXXXXX,ravi@example.com"
```
This also gives the parent a demo customer record at each of the five fictional member businesses
(refresh them any time with `--records-only`). Then message the Kavach number from the parent's phone; try the
member-business messages in [docs/DEMO.md](docs/DEMO.md), or every feature with copy-paste test messages in
[docs/TESTING.md](docs/TESTING.md). Or test without WhatsApp:
`python scripts/ask_agent.py --arn <ARN> --phone +9198XXXXXXXX "Is this real? Your SBI account will be blocked, update KYC at sbi-kyc-update.xyz"`

### 5. Optional: forwarded-email checking
Verify a domain in SES **Singapore**, add an MX record to `inbound-smtp.ap-southeast-1.amazonaws.com`, then:
```bash
sam build -t email-inbound.yaml && sam deploy -t email-inbound.yaml --guided --region ap-southeast-1
aws ses set-active-receipt-rule-set --rule-set-name kavach-inbound --region ap-southeast-1
```

## Safety and privacy
- Consent is collected on WhatsApp before any check; `STOP` pauses Kavach and `hi` turns it back on.
- Each member service a person is linked to is listed in Settings > Linked services, with what it shares, and can
  be unlinked there.
- Media is deleted from S3 after 7 days. Community reports store the scammer's identifiers, never the
  reporter's number.
- Text inside screenshots and web pages is treated as untrusted evidence, never as instructions.
- Kavach never asks for OTPs, PINs or passwords, and does not fill or submit forms when it opens links.

## License
MIT. See [LICENSE](LICENSE).
