# Testing Kavach: every feature, with messages to send

Each test lists what to send and what should happen. Messages are in boxes so you can copy them on a phone.

## Before you start

- **Deploy and seed** first (README "Setup"). The seed command makes the parent's number "Amma" (Telugu, already
  agreed to the terms), adds Ravi as her guardian, pre-loads two community scam reports (`sbi-kyc-update.xyz` and
  `refund.help.desk@ybl`), and gives Amma a customer record at the five **fictional** member businesses:
  ```bash
  python scripts/seed_demo.py --parent "+91<Amma's number>" --name "Lakshmi Amma" --language te \
    --district Kurnool --bank SBI --guardian "Ravi,+91<Ravi's number>,<Ravi's email>"
  ```
  Re-run with `--records-only` on the day you test, because demo dates (refill due, last debit, cleaning
  booking) are counted from the seed day.
- **Phones:** *Amma* = the seeded parent number. *Ravi* = a second phone, the guardian (any family member's phone
  works). *Kavach* = the Kavach WhatsApp number (+91 62990 26473 in our deployment). If Amma's number is also in
  `OpsOwnerPhones`, the same phone can run the ops tests in section 9.
- **Forward scam texts, don't paste them**, where you can. Kavach treats forwarded text as someone else's words. If
  you paste "Sir, I sent you ₹5,000 by mistake", Kavach may think *you* paid and ask about it.
- **Replies take 20 to 60 seconds.** The first message after a deploy is slower.
- **Actions are real.** Family alerts go to Ravi's phone and email, fraud reports go to the fraud-desk inbox, and
  scam identifiers are added to the community reports.
- **Language:** Amma's replies come in Telugu. Send `English` to switch while testing, and `తెలుగు` to switch back.
- **Messages starting with `aws`** typed from the owner's number go to ops mode, not the scam check.

---

## 1. Onboarding and settings (any time, no commands to remember)

**A1. A new person says hi** (from a phone Kavach has never seen)
```text
hi
```
Expect: language buttons (తెలుగు / हिन्दी / English), then the consent message with **I agree** / **No thanks**,
then the welcome message with two buttons: **Add family member** and **Settings**.

**A2. Open settings.** Send any of these (or `hi` once you are set up):
```text
MENU
```
```text
మెనూ
```
Expect: one list, **Open settings**, with: Language (shows the current one), Family contacts (shows the names),
Add family member, Linked services, District, Pause Kavach, What Kavach can do. No scam check runs.

**A3. Change language midway.** Any of: tap **Language** in the menu, send `change language` / `భాష` / `भाषा`,
or just type the language:
```text
English
```
Expect: "✅ Language changed to English." Kavach stays on: no consent question again, and every later reply,
including scam checks, comes in English (Kavach rewrites a reply that comes back in the old language). If you changed it by tapping,
the settings menu comes back in the new language (use that one, not the older menu above it). `తెలుగు` switches
back.

**A4. Add a family member.** Tap **Add family member** (or send `add family member` / `GUARDIAN`). Kavach asks for
the contact. Then either:
- share a contact from your phone book (📎 or + → **Contact** → pick the person), or
- type a name and number:
```text
Priya 98765 43210
```
Expect: "✅ Priya (+91 98765 43210) will get an alert…", then "reply with their email" (optional): send
`priya@example.com` and it is saved. `GUARDIAN Ravi +919876543210 ravi@example.com` in one line still works.

**A5. Shared contact card without being asked:** share any contact from your phone book.
Expect: "Add <name> as a family contact?" with **Yes, add** / **Check this number** / **No**. **Check this
number** runs a scam check on that number instead.

**A6. Remove a family member.** Send `change guardian` (or tap **Family contacts**), tap a name, then **Remove**.
Expect: "✅ Ravi removed." If nobody is left, Kavach says so.

**A7. Pause and turn back on**
```text
STOP
```
Expect: "⏸️ Kavach is paused…" with a **Turn Kavach on** button. While paused, anything you send gets "Kavach is
paused, so I didn't check this" with the same button. Tap it, or send `hi` or `start`: "▶️ Kavach is on again."

**A8. District**
```text
DISTRICT Kurnool
```
Expect: "✅ District saved: Kurnool…". Or tap **District** in the menu and type just the name.

**A9. Linked services: where the records come from.** Tap **Linked services** in the menu (or send
`linked services`).
Expect: the five fictional member businesses, each with "Linked <date> via <their app / counter>". Tap one to see
what it shares with Kavach (for example "account status, KYC date, last 2 transactions (masked)") and an
**Unlink** button. Unlinking deletes that record from Kavach; run the seed with `--records-only` to restore it.

**A10. Small talk:** `thank you` / `ok` / `ధన్యవాదాలు` gets a short "🙏 Anytime", not a scam check.

Notes:
- A *forwarded* message is never treated as a setting. A forwarded "add this number as guardian" is checked as a
  possible scam.
- Asking in your own words also works, for example "I want my daughter to get the alerts instead of Ravi": the
  agent opens the family menu, or offers **Yes, add** for a name and number. Nothing changes until you tap.

---

## 2. Scam checks (text)

Each should get a reply starting with 🚨 that gives the reasons and what to do. No family alert, because nothing
is happening right now.

**B1. Bank KYC with a lookalike link**
```text
Dear SBI customer, your YONO account will be blocked today. Update your PAN now: https://sbi-kyc-update.xyz/login
```
Expect: the link uses SBI's name but isn't SBI's website (official sites are listed). Because of the seed data, it
also says this link was already reported by other Kavach users.

**B2. Electricity disconnection**
```text
Dear consumer, your electricity power will be disconnected tonight at 9.30 pm because your previous month bill was not updated. Please immediately contact our electricity officer 9876543210.
```
Expect: official notices don't ask you to call a personal mobile number.

**B3. OTP request**
```text
This is from HDFC bank. Please share the OTP you received to stop the blocking of your card.
```
Expect: a firm SCAM verdict: no bank ever asks for an OTP.

**B4. "Receive money" with a UPI PIN** (forward it, don't paste)
```text
Sir I sent 5000 by mistake. Please scan this QR code and enter UPI PIN to receive refund. UPI refund.help.desk@ybl
```
Expect: you never need a PIN or a QR scan to receive money; the UPI ID was already reported.

**B5. App file (.apk)**
```text
Your RTO e-challan is pending. Download the app to pay: https://echallan-pay.top/RTO_Challan.apk
```
Expect: a SCAM verdict: government departments don't send .apk apps, and the site isn't parivahan.gov.in.

**B6. Lottery fee**
```text
Congratulations! You have won Rs 25 lakh in the KBC lucky draw. Pay processing fee Rs 12,500 to claim.
```
Expect: genuine prizes never ask for a fee first.

**B7. Guaranteed returns**
```text
Join our VIP stock group. Guaranteed returns of 5% daily profit on your investment.
```
Expect: no real investment guarantees returns; check advisers on SEBI's website.

**B8. Screen-sharing app**
```text
Install AnyDesk so our bank executive can fix your net banking.
```
Expect: a SCAM verdict: screen-sharing apps let the other person see your OTPs.

**B9. Digital arrest in Hindi** (Telugu is in test D3)
```text
मुझे सीबीआई से वीडियो कॉल आया, बोले मनी लॉन्ड्रिंग केस है, किसी को मत बताना।
```
Expect: a SCAM verdict: "digital arrest" doesn't exist in Indian law; hang up. Because this sounds like it's
happening now, Kavach may also alert Ravi (see test E1).

---

## 3. Genuine messages (should NOT be called scams)

**C1. A real bank OTP SMS**
```text
123456 is your OTP for transaction of Rs 2,500 at Amazon. Do not share this OTP with anyone. - HDFC Bank
```
Expect: no 🚨. At most a reminder never to share the OTP.

**C2. A real government website**
```text
Is this the real India Post website? https://www.indiapost.gov.in
```
Expect: ✅ looks genuine (.gov.in is a protected government domain). Kavach may open it in AgentCore Browser first.

**C3. A news story about scams**
```text
Hyderabad police arrested a gang running digital arrest scams over video call. Beware of such calls.
```
Expect: no 🚨. Kavach recognises it as news or awareness, not a scam aimed at you.

**C4. A family message**
```text
Amma, I reached Bengaluru safely. Will call you tonight.
```
Expect: nothing suspicious.

---

## 4. Photos, PDFs and voice notes

**D1. Screenshot of a scam SMS:** take a screenshot of B1 or B2 and send it.
Expect: the same verdict as the text. Kavach reads the text inside the image.

**D2. A PDF "notice":** send any PDF that looks like a police, court or bank notice.
Expect: Kavach summarises what it claims, and points out forgery signs and red flags (WhatsApp is not how courts or
police send notices).

**D3. Telugu voice note:** record and send this as a voice note:
> ఇప్పుడు నాకు సీబీఐ నుంచి వీడియో కాల్ వచ్చింది. నా ఆధార్ మనీ లాండరింగ్ కేసులో ఉందని, డబ్బు పంపమంటున్నారు. ఎవరికీ చెప్పొద్దన్నారు.

Expect: Amazon Transcribe turns it into text, then a SCAM reply in Telugu telling her to hang up, and a family
alert (E1).

**D4. An .apk file:** send any file ending in `.apk` as a document.
Expect: a SCAM verdict: never install apps sent on WhatsApp.

---

## 5. Family alert and escalation

Family alerts are only for danger happening **now**, described in the person's own words: a "police/CBI" call,
being asked to install a screen-sharing app or to pay an "official", or money already sent (section 6). A
forwarded scam text she hasn't acted on gets a 🚨 reply but no family alert.

**E0. Test alert first.** Send `MENU`, tap **Family contacts**, then **🔔 Send a test alert**.
Expect, on Amma's phone: "🔔 Test alert:" with ✅ or ❌ (and WhatsApp's reason) for each family member. Each family
member gets a Kavach alert marked as a test; when they tap a button, Amma gets "✅ Ravi received the test alert".
If WhatsApp rejects it a few seconds later (for example the family member hasn't messaged Kavach in 24 hours and
the template isn't approved), Amma gets "⚠️ The alert to Ravi didn't reach them…" with the reason.

**E1. Danger right now.** First send `hi` from Ravi's phone (this opens WhatsApp's 24-hour window, so Ravi gets a
normal message with buttons even if the alert template isn't approved). Then, from Amma's phone, send D3 as a
voice note, or type:
```text
I am on a video call with CBI officers now. They say my Aadhaar is in a money laundering case and I must transfer money for verification.
```
Expect:
- Amma: "hang up now" and "👨‍👩‍👧 I have alerted Ravi. They will call you." If WhatsApp refused it, she is
  told so instead ("⚠️ I couldn't reach Ravi on WhatsApp. Please call them yourself.").
- Ravi: a 🚨 Kavach alert with **I'm calling now** / **I've reached them**, plus an email (only if Ravi's email is
  verified in SES while SES is in sandbox mode).
- Ravi taps **I'm calling now** → Amma gets "Ravi has seen the alert and is calling you now", and Ravi gets an
  **I've reached them** button.
- If nobody taps: Ravi is alerted again at **5 minutes**, and gets a final email at **10 minutes**.
- Ravi taps **I've reached them** → the alert is closed.

If Ravi gets nothing:
- From the owner's phone, send `aws is kavach healthy?`. The reply lists template approval status and
  "WhatsApp delivery failures" (for example `131047 Re-engagement message`: Ravi hasn't messaged Kavach in 24
  hours and the template isn't approved; or `132001`: the template name or language doesn't match).
- Or search the logs (Git Bash):
  ```bash
  MSYS_NO_PATHCONV=1 aws logs filter-log-events --region ap-south-1 --log-group-name /aws/lambda/kavach-inbound \
    --start-time $(( ($(date +%s) - 3600) * 1000 )) --filter-pattern '"DELIVERY FAILED"' --query 'events[].message'
  ```
- If Ravi is the same number as Amma (testing with one phone), the alert arrives in the same chat.

---

## 6. Golden hour (money already sent)

**F1.** Make a real ₹1 UPI payment between two of your own accounts and screenshot the receipt. Send the screenshot
with this caption (or send the text alone):
```text
They said they are from CBI. I already paid Rs 10,000 to rbi.verify@ybl just now on PhonePe.
```
Expect:
- A ready-to-use complaint text for 1930 / cybercrime.gov.in (amount, UTR, payee, time).
- A fraud report emailed to the fraud-desk inbox and to Ravi, and a WhatsApp alert to Ravi.
- "Call 1930 right now" in the reply.
- **15 minutes later:** "Did you call 1930?" with **Yes, I called** / **Not yet, help me**. Each button gives the
  next steps.

---

## 7. Member businesses (fictional, checked against Amma's demo records)

After each verdict, Kavach sends that business's buttons. Scam verdicts include **Report this scam**.

**G1. Kalpavi Bank: fake KYC block**
```text
Kalpavi Bank: Dear customer, your account will be blocked today as your KYC has expired. Update KYC now: kalpavi-kyc.top/update
```
Expect: 🚨. Kalpavi's records show account XX4821 active and KYC valid until 31 Mar 2028; the link isn't
kalpavi.bank.in. Buttons: **My account status**, **Call me back**, **Report this scam**.

**G2. Kalpavi Bank: fake debit alert**
```text
Kalpavi Bank alert: Rs 49,999 debited from your account. If not done by you, call our officer on 9876543210 immediately.
```
Expect: 🚨. No such transaction in her records, and banks don't ask you to call a personal mobile.

**G3. Kalpavi Bank: a genuine debit SMS**
```text
VM-KLPAVI-S: Rs 2,000.00 debited from A/c XX4821 via UPI to Sri Lakshmi Kirana. Not you? Call the number on the back of your card. - Kalpavi Bank
```
Expect: looks genuine. It matches her records (₹2,000 UPI to Sri Lakshmi Kirana) and Kalpavi's registered sender ID.

**G4. Nidhira Health Insurance: fake "policy lapse"** (the demo-video scene)
```text
Dear Nidhira Health customer, your policy NHI-2025-004471 will lapse today. Pay premium Rs 14,200 now at https://nidhira-renew.xyz or UPI nidhira.renewal@ybl to keep your cover.
```
Expect: 🚨. Nidhira confirms the policy is active until 31 Mar 2027. The ₹14,200 is her real premium, but it isn't
due until 15 Mar 2027. Buttons: **My real policy**, **Call me back**, **Report this scam**.
- **My real policy** → her real policy details, in her language.
- **Report this scam** → an impersonation report (fake site, UPI ID) lands in the fraud-desk inbox.
- **Call me back** → a call-back request email; Amma is told Nidhira will call from a number starting with 1600.

**G5. Nidhira in Telugu**
```text
నిధిరా హెల్త్ పాలసీ ఈరోజు రద్దు అవుతుంది. వెంటనే చెల్లించండి
```
Expect: 🚨, with the same record check.

**G6. Nidhira: a genuine renewal reminder**
```text
Nidhira Health Insurance: premium of Rs 14,200 for policy NHI-2025-004471 is due on 15 Mar 2027. Renew in the Nidhira app or at https://nidhirahealth.in
```
Expect: looks genuine (official website, and the date matches her record).

**G7. Dawaghar Pharmacy: fake payment hold**
```text
Dawaghar Pharmacy: your medicine order is on hold due to pending payment of Rs 1,250. Pay now at https://dawaghar-pay.top to avoid cancellation.
```
Expect: 🚨. Nothing is out for delivery; her next refill is ₹412, paid on delivery. Buttons: **Reserve my refill**,
**My medicines**, **Report this scam**. **Reserve my refill** confirms the refill, payable on delivery.

**G8. Dawaghar: a genuine refill reminder**
```text
Dawaghar: your Metformin 500 mg refill (Rs 412) is due this week. Pay on delivery.
```
Expect: looks genuine (it matches her record).

**G9. Chamak Home Services: fake advance payment**
```text
Chamak Home Services: your deep cleaning slot on Saturday is pending. Pay Rs 999 advance to chamak.booking@okaxis within 1 hour, else your booking will be cancelled.
```
Expect: 🚨. Her booking is confirmed, and Chamak never takes advances. **Check my booking** shows the booking and the
4-digit **visit code** the cleaner must say at the door.

**G10. Dhanvi Family Clinic: fake booking fee**
```text
Dhanvi Clinic: pay Rs 500 advance to confirm your appointment, else your booking will be cancelled. UPI dhanvi.desk@ybl
```
Expect: 🚨. The clinic never takes advances; fees are paid at the reception after the visit. Buttons:
**Book appointment**, **My appointments**, **Report this scam**.

**G11. Not a customer:** send G4 from Ravi's phone (he has no demo records).
Expect: still 🚨 (fake site, unofficial UPI), but Kavach says it couldn't find his Nidhira record. Only **Call me
back** / **Report this scam** are offered.

---

## 8. Everyday help

**H1. A product ad:** screenshot any social-media ad for a branded product showing a big "% OFF", and send it with:
```text
Is this a good deal? I want to buy it.
```
Expect: links to the product on amazon.in and flipkart.com, and a warning if the ad claims 70% off or more from an
unknown seller. Kavach can't order on Amazon for you.

**H2. Buy something by name**
```text
I want to buy a Prestige 5 litre pressure cooker
```
Expect: amazon.in and flipkart.com search links, and "buy only in the official app".

**H3. Book a doctor for a problem**
```text
I need to see a doctor for my knee pain
```
Expect: a reply naming the doctor, then a WhatsApp list (**Choose a time**) of Dr. P. Lakshmi's free times. The
list is always sent for a request like this, and the reply never tells you to tap a button that isn't there. If
no time is free, you get a **Call me back** button instead. Tap a time:
- Amma: "✅ Appointment booked … Token N … pay ₹500 at the reception after your visit".
- Ravi (and Amma, if she has an email): a booking email.
- A reminder with **I'm on my way** / **Cancel visit**, 2 hours before (30 minutes before if booked less than 2
  hours ahead).

Clinic hours (Dhanvi Family Clinic, fictional; closed Sundays):

| Doctor | For | Days | Hours | Fee |
| --- | --- | --- | --- | --- |
| Dr. K. Srinivasa Rao | General (fever, cold, BP, sugar) | Mon-Sat | 10:00-13:00, 17:00-20:00 | ₹400 |
| Dr. P. Lakshmi | Bones and joints (knee, back) | Mon, Wed, Fri, Sat | 11:00-14:00 | ₹500 |
| Dr. S. Imran | Eyes (vision, glasses) | Tue, Thu, Sat | 16:00-19:00 | ₹450 |

To see the reminder quickly, book a time about 2 hours 15 minutes ahead: it arrives about 15 minutes later.

**H4. Other doctors**
```text
I have fever since yesterday
```
```text
Eye check-up for new glasses
```
Expect: Dr. Rao's times; Dr. Imran's times.

**H5. My appointments / cancel**
```text
What are my appointments?
```
```text
Cancel my appointment
```
Expect: the upcoming booking with its token; then a cancellation confirmation (the slot becomes free again).

**H6. Two people, one slot:** tap the same time from Amma's list on two phones.
Expect: only the first is booked; the second gets "that time was just taken" and fresh times.

---

## 9. Ops mode (owner's number only, typed, not forwarded)

**I1.**
```text
aws are my WhatsApp templates approved?
```
Expect: each template's status, whether SES is still in sandbox mode, Lambda errors and today's checks.

**I2.**
```text
aws how much have I spent this month?
```
Expect: the month-to-date total and top services. This needs Cost Explorer enabled once in the Billing console.

**I3.**
```text
aws which instances are running?
```
Expect: your EC2 instances in the regions you set in `OpsRegions`.

**I4.** (only with a spare instance) `aws stop <instance name>`
Expect: "Stop <name> (i-…)?" with **Yes, do it** / **Cancel**. Nothing changes until you tap Yes. A second tap
says it was already handled.

**I5. Refused actions**
```text
aws delete my S3 bucket
```
Expect: a refusal. Ops mode can't delete, terminate or change security.

**I6. Not the owner:** send I1 from Ravi's phone.
Expect: treated as a normal message, not ops mode.

---

## 10. Community warnings, family digest, repeat reports

**J1. District scam-wave warning** (Git Bash):
```bash
python scripts/trigger_scam_wave.py --district Kurnool --summary "fake electricity disconnection messages asking you to call an officer"
```
Expect: every active user in Kurnool gets a WhatsApp warning (a template, or a normal message inside the 24-hour
window). This also happens automatically after 3 real reports of one scam type in a district within 24 hours.

**J2. Sunday family digest, now** (Git Bash):
```bash
aws lambda invoke --function-name kavach-weekly-digest --region ap-south-1 --cli-binary-format raw-in-base64-out --payload '{"phone":"+919121095635"}' out.json
```
Expect: Ravi gets an email summarising Amma's week.

**J3. Repeat reports:** send B1 twice.
Expect: the second time, the community-report count is higher. Scam links, numbers and UPI IDs from SCAM verdicts are
stored for 90 days.

---

## 11. Without WhatsApp

```bash
python scripts/ask_agent.py --arn <runtime ARN> --phone +919121095635 "Dear SBI customer, your YONO account will be blocked today. Update your PAN now: https://sbi-kyc-update.xyz/login"
```
Expect: the reply, plus the final verdict, what the model said, the rules' minimum verdict, the red flags, buttons and
timings. Tools still act for real.

---

## What Kavach does not do (yet)

- Order on Amazon or Flipkart: there's no ordering API for outside apps. It sends official links instead.
- Order food: Swiggy was built and removed; it needs Swiggy's approval.
- SMS or a per-person channel choice: everything goes over WhatsApp and email for now.
- Languages beyond Telugu, Hindi and English.
- Real businesses: the five member businesses and their records are fictional demo data.
- Email anyone not verified in SES, while SES is in sandbox mode.
