# Kavach demo kit

Three phones on screen: **Amma** (protected parent, Telugu), **Ravi** (son), and a laptop showing
Ravi's email inbox plus the "bank fraud desk" inbox. Record each phone's screen and edit them side by side.

## Messages to send from Amma's phone

Send these from a phone that is NOT the Kavach number. Use WhatsApp's forward button where possible, so
Kavach sees "forwarded".

**1. Electricity disconnection (expect: scam, no family alert)**
> Dear consumer, your electricity power will be disconnected tonight at 9.30 pm from the electricity office
> because your previous month bill was not updated. Please immediately contact our electricity officer
> 98XXXXXXXX. Thank you.

(Put any number you control in place of 98XXXXXXXX.)

**2. Bank KYC lookalike link (expect: scam, "LOOKALIKE" domain signal)**
> Dear SBI customer, your YONO account will be blocked today. Update your PAN immediately:
> https://sbi-kyc-update.xyz/login

**3. A genuine link (expect: looks genuine, opened in AgentCore Browser)**
> Is this the right site to track my parcel? https://www.indiapost.gov.in

**4. Digital arrest, as a Telugu voice note (expect: critical, family alerted, 5-minute escalation)**
Record and send as a voice note:
> ఇప్పుడు నాకు సీబీఐ నుంచి వీడియో కాల్ వచ్చింది. నా ఆధార్ మనీ లాండరింగ్ కేసులో ఉందని,
> డబ్బు వెరిఫికేషన్ కోసం పంపమంటున్నారు. ఎవరికీ చెప్పొద్దన్నారు.

(English: "I just got a video call from CBI. They say my Aadhaar is in a money-laundering case and want
me to send money for verification. They told me not to tell anyone.")

**5. Money already sent (expect: golden-hour flow)**
Make a real ₹1 UPI payment between two of your own accounts, screenshot the receipt, and send it with:
> I already paid them 10 minutes ago. They said it's for RBI verification.

Kavach reads the amount, UTR and recipient from the screenshot, sends the complaint text, emails the bank
desk and family, alerts Ravi, and asks "Did you call 1930?" 15 minutes later.

## Member businesses (the four are fictional)

`seed_demo.py` gives Amma a customer record at Kalpavi Bank, Nidhira Health Insurance, Dawaghar Pharmacy
and Chamak Home Services. After each verdict, Kavach sends that business's buttons.

**6. Insurance "lapse" (expect: scam; "Nidhira confirms your policy is active until 31 Mar 2027")**
> Dear Nidhira Health customer, your policy NHI-2025-004471 will lapse today. Pay premium Rs 14,200 now at
> https://nidhira-renew.xyz or UPI nidhira.renewal@ybl to keep your cover.

The amount is her real premium (as if leaked), but Kavach sees it isn't due until 15 Mar 2027. Tap
**My real policy** (her real details, in Telugu), then **Report this scam** (the fraud desk inbox gets an
impersonation report with the fake site and UPI ID).

**7. Cleaning advance (expect: scam; booking confirmed, Chamak never takes advances)**
> Chamak Home Services: your deep cleaning slot on Saturday is pending. Pay Rs 999 advance to
> chamak.booking@okaxis within 1 hour, else your booking will be cancelled.

Tap **Check my booking**: the real booking plus the visit code the professional will say at the door.

**8. Pharmacy payment hold (expect: scam; nothing out for delivery, the real refill is ₹412 on delivery)**
> Dawaghar Pharmacy: your medicine order is on hold due to pending payment of Rs 1,250. Pay now at
> https://dawaghar-pay.top to avoid cancellation.

Tap **Reserve my refill**.

**9. A genuine bank SMS (expect: looks genuine; "matches Kalpavi Bank's records")**
> VM-KLPAVI-S: Rs 2,000.00 debited from A/c XX4821 via UPI to Sri Lakshmi Kirana. Not you? Call the
> number on the back of your card. - Kalpavi Bank

## 3-minute video outline

| Time | Scene | What judges should notice |
| --- | --- | --- |
| 0:00-0:15 | Problem: ₹22,495 crore lost in 2025; digital arrest targets the elderly | Real, Indian, daily |
| 0:15-0:35 | Amma forwards message 1 and gets a Telugu verdict | WhatsApp in, reasoning, reply in her language |
| 0:35-0:55 | Message 2: lookalike domain caught; message 3: real site checked in the browser | Agent tools, AgentCore Browser |
| 0:55-1:35 | Message 6: "Nidhira confirms your policy is active"; tap My real policy; tap Report, the fraud desk email arrives | Checked against the business's records, one-tap real action, signal back to the business |
| 1:35-2:10 | Voice note 4: Ravi's phone lights up with the alert template; he taps "I'm calling now"; Amma is told | Family loop, buttons, escalation timer |
| 2:10-2:35 | Screenshot 5: golden-hour flow, bank email arrives, 1930 check-in | SES + WhatsApp working together |
| 2:35-3:00 | Architecture diagram + district scam warning; "any bank, insurer, pharmacy or service company can join" | Multiple CDS services, a repeatable partner offering |

Run `python scripts/trigger_scam_wave.py --district Kurnool --summary "fake electricity disconnection messages asking you to call an officer"`
and invoke `kavach-weekly-digest` with `{"phone": "+91..."}` to film the warning and digest without waiting.
