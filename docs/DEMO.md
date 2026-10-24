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

## Member businesses (all five are fictional)

`seed_demo.py` gives Amma a customer record at Kalpavi Bank, Nidhira Health Insurance, Dawaghar Pharmacy,
Chamak Home Services and Dhanvi Family Clinic. After each verdict, Kavach sends that business's buttons.

**Where do these records come from?** Each business joined Kavach and, with Amma's consent (in its own app, at
its counter or when she renewed her policy), linked her record to the mobile number registered with it, which is
the same number as her WhatsApp. WhatsApp itself verified that number when she installed it, so a message from
that number can only come from her phone. Kavach only ever sees a small slice (status, due dates, a masked recent
transaction), never passwords, PINs or OTPs. Show this on camera before message 6:

**5b. "How does Kavach know?" (expect: a list of linked services with dates and channels)**
Send `MENU`, tap **Linked services**, then **Nidhira Health Insurance**: "Linked <date> via Nidhira policy
renewal. Kavach can see: policy status, cover end date, next premium", with an **Unlink** button.

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

## Everyday help

**10. A product ad (expect: links to the real amazon.in and flipkart.com, a discount warning)**
Screenshot any social-media ad for a branded product with a big "% OFF" and send it with:
> Is this a good deal? I want to buy it.

**11. A doctor's appointment (expect: Dr. P. Lakshmi, a list of times; tap one)**
> I need to see a doctor for my knee pain

Tap a time: Amma gets the confirmation and token, Ravi's inbox gets the email, and a reminder arrives
2 hours before (book a slot about 2 hours 15 minutes ahead to see it during filming). Dhanvi is a member clinic:
it shares its doctors' timetable with Kavach and takes bookings through it. Today there is one demo clinic in
Kurnool; more member clinics would be matched by the district Amma set.

**SOS (expect: Ravi's phone gets the alert in seconds, then a map pin)**
Send `HELP`. Ravi's phone lights up with the SOS alert; Amma taps **Send location**; Ravi gets the pin and a Maps
link; Amma taps **I'm safe now** and Ravi is told. Good for a 15-second shot after the digital-arrest scene.

**12. Settings in her own words (expect: no commands to type)**
Send `English`, then `తెలుగు` (language switches, Kavach stays on). Share Ravi's contact card from the phone book
and tap **Yes, add**. Send `STOP`, then `hi`.

## 3-minute video outline

| Time | Scene | What judges should notice |
| --- | --- | --- |
| 0:00-0:15 | Problem: ₹22,495 crore lost to cyber fraud in 2025; over ₹3,000 crore to digital arrests, mostly the elderly | Real, Indian, daily |
| 0:15-0:45 | Message 2: SBI lookalike link, Telugu verdict | WhatsApp in, evidence first, reply in her language |
| 0:45-1:30 | 5b for 5 seconds (Linked services: her insurer linked her policy to this number, with her consent). Then message 6: "Nidhira confirms your policy is active"; tap My real policy; tap Report, the fraud desk email arrives | Where the data comes from, checked against the business's records, one-tap real action, WhatsApp to email |
| 1:30-2:10 | Voice note 4: Ravi's phone lights up; he taps "I'm calling now"; Amma is told | End-to-end agentic loop, family buttons, escalation timer |
| 2:10-2:30 | Screenshot 5: complaint text, bank email, "Did you call 1930?" 15 minutes later | WhatsApp, SES and timers together |
| 2:30-3:00 | Architecture diagram; "any bank, insurer, pharmacy or service company can run Kavach" | Several CDS services with AWS AI services; a partner offering |

Before recording: if the WhatsApp templates aren't approved yet, have Ravi's phone message Kavach first, so
his alert can go as a normal message inside the 24-hour window. Blur real phone numbers in the edit.

Run `python scripts/trigger_scam_wave.py --district Kurnool --summary "fake electricity disconnection messages asking you to call an officer"`
and invoke `kavach-weekly-digest` with `{"phone": "+91..."}` to film the warning and digest without waiting.
