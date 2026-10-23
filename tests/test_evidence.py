"""The fixed rules: scams must raise the floor, genuine messages must not."""
import pytest

import evidence as ev

USER = "+919800000001"

SCAMS = [
    ("sbi_kyc", "Dear SBI customer, your YONO account will be blocked today. Update your PAN now: "
                "https://sbi-kyc-update.xyz/login", "LIKELY_SCAM", {"lookalike_domain"}),
    ("electricity", "Dear consumer, your electricity power will be disconnected tonight at 9.30 pm because your "
                    "previous month bill was not updated. Please immediately contact our electricity officer "
                    "9876543210.", "LIKELY_SCAM", {"personal_number_for_institution"}),
    ("digital_arrest_te", "ఇప్పుడు నాకు సీబీఐ నుంచి వీడియో కాల్ వచ్చింది. నా ఆధార్ మనీ లాండరింగ్ కేసులో ఉందని, "
                          "డబ్బు పంపమంటున్నారు. ఎవరికీ చెప్పొద్దన్నారు.", "SCAM", {"digital_arrest"}),
    ("digital_arrest_hi", "मुझे सीबीआई से वीडियो कॉल आया, बोले मनी लॉन्ड्रिंग केस है, किसी को मत बताना।", "SCAM",
     {"digital_arrest"}),
    ("upi_receive", "Sir I sent 5000 by mistake. Please scan this QR code and enter UPI PIN to receive refund. "
                    "UPI refund.help@ybl", "LIKELY_SCAM", {"pin_to_receive"}),
    ("otp_ask", "This is from HDFC bank. Please share the OTP you received to stop the blocking of your card.",
     "SCAM", {"asks_for_otp"}),
    ("apk", "Your RTO e-challan is pending. Download the app to pay: https://echallan-pay.top/RTO_Challan.apk",
     "SCAM", {"apk_file"}),
    ("authority_upi", "They said they are from CBI. I already paid Rs 49,999 to rbi.verify@ybl", "LIKELY_SCAM",
     {"authority_upi", "authority_asks_money"}),
    ("lottery", "Congratulations! You have won Rs 25 lakh in the KBC lucky draw. Pay processing fee Rs 12,500 to "
                "claim.", "LIKELY_SCAM", {"fee_for_prize"}),
    ("investment", "Join our VIP stock group. Guaranteed returns of 5% daily profit on your investment.",
     "LIKELY_SCAM", {"guaranteed_returns"}),
    ("remote", "Install AnyDesk so our bank executive can fix your net banking.", "SCAM", {"remote_access_app"}),
]

GENUINE = [
    ("bank_otp", "123456 is your OTP for transaction of Rs 2,500 at Amazon. Do not share this OTP with anyone. "
                 "- HDFC Bank"),
    ("bank_debit", "Rs 500.00 debited from A/c XX1234 on 22-10-26. If not done by you, SMS BLOCK to 9223008333 "
                   "or call 1800 1234 - SBI"),
    ("gov_site", "Is this the real India Post website? https://www.indiapost.gov.in"),
    ("delivery_pincode", "Please share your full address with pin code for delivery of your Flipkart order"),
    ("news", "Hyderabad police arrested a gang running digital arrest scams over video call. Beware of such calls."),
    ("family", "Amma, I reached Bengaluru safely. Will call you tonight."),
    ("email", "Contact ravi@example.com for the wedding photos"),
]


@pytest.mark.parametrize("name,text,floor,rules", SCAMS, ids=[c[0] for c in SCAMS])
def test_scams_raise_the_floor(name, text, floor, rules):
    e = ev.build(text, user_phone=USER)
    fired = {f["rule"] for f in e["red_flags"]}
    assert rules <= fired, f"{name}: expected {rules}, got {fired}"
    assert ev.VERDICT_ORDER.index(e["verdict_floor"]) >= ev.VERDICT_ORDER.index(floor)


@pytest.mark.parametrize("name,text", GENUINE, ids=[c[0] for c in GENUINE])
def test_genuine_messages_have_no_floor(name, text):
    e = ev.build(text, user_phone=USER)
    assert e["verdict_floor"] is None, f"{name}: unexpected flags {e['red_flags']}"


def test_extraction():
    ex = ev.extract("Pay to refund.help@ybl or visit sbi-help.in. Call +91 98765 43210 or 1600123456. "
                    "Mail ravi@example.com. Amount ₹1,500.")
    assert [l["domain"] for l in ex["links"]] == ["sbi-help.in"]
    assert ex["upi_ids"] == ["refund.help@ybl"]
    assert ex["mobile_numbers"] == ["+919876543210"]
    assert ex["special_numbers"] == ["1600123456"]
    assert ex["amounts_inr"] == ["1500"]


def test_own_numbers_are_not_suspects():
    e = ev.build("Call me on 9800000001 Amma", user_phone=USER)
    assert e["extracted"]["mobile_numbers"] == []


def test_forwarded_text_does_not_suggest_money_loss():
    text = "Sir I sent 5000 by mistake to you, please return it"
    assert ev.build(text, user_phone=USER, forwarded=True)["suggested_actions"] == []
    assert ev.build("I already paid them 5000", user_phone=USER)["suggested_actions"]


def test_reply_grounding():
    ctx = "User's message: https://sbi-kyc-update.xyz/login Rs 2,500. official: sbi.co.in"
    assert ev.ungrounded_contacts("🚨 sbi-kyc-update.xyz నకిలీ. 1930కి కాల్ చేయండి. Visit sbi.co.in.", ctx) == []
    bad = ev.ungrounded_contacts("Call SBI customer care at 1800 1234 or visit www.sbi-help.in. "
                                 "Or call 9988776655.", ctx)
    assert {"sbi-help.in", "+919988776655", "1800", "1234"} <= set(bad)
    assert ev.ungrounded_contacts("1930 पर कॉल करें। 155260 पर भी कॉल करें।", ctx) == ["155260"]
    assert ev.ungrounded_contacts("The Rs 2,500 was debited; report at cybercrime.gov.in", ctx) == []
