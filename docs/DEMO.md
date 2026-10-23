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

## 3-minute video outline

| Time | Scene | What judges should notice |
| --- | --- | --- |
| 0:00-0:20 | Problem: ₹22,495 crore lost in 2025; digital arrest targets the elderly | Real, Indian, daily |
| 0:20-0:45 | Amma forwards message 1 and gets a Telugu verdict | WhatsApp in, reasoning, reply in her language |
| 0:45-1:10 | Message 2: lookalike domain caught; message 3: real site checked in the browser | Agent tools, AgentCore Browser |
| 1:10-1:55 | Voice note 4: Ravi's phone lights up with the alert template; he taps "I'm calling now"; Amma is told | Family loop, buttons, escalation timer |
| 1:55-2:30 | Screenshot 5: golden-hour flow, bank email arrives, 1930 check-in | SES + WhatsApp working together |
| 2:30-2:50 | Architecture diagram + Sunday digest email + district scam warning | Multiple CDS services, well integrated |
| 2:50-3:00 | Business: banks and UPI apps offer "Kavach for <brand>" | Repeatable partner offering |

Run `python scripts/trigger_scam_wave.py --district Kurnool --summary "fake electricity disconnection messages asking you to call an officer"`
and invoke `kavach-weekly-digest` with `{"phone": "+91..."}` to film the warning and digest without waiting.
