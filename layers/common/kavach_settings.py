"""Settings the person can change any time, in their own language, without typing commands.

"MENU" (or "hi" once they are set up) opens a WhatsApp list: language, family contacts, add a family member,
linked services, district, pause or turn on, and examples. Short requests work too, in Telugu, Hindi or
English: "change language", "భాష", "हिंदी", "STOP", "add Ravi 98765 43210". A contact card shared from
the phone book adds a family member.

Everything here is plain code with no model call. The agent can open these menus (tools/settings.py), but a
change only happens when the person taps or types it themselves.
"""
from __future__ import annotations

import re
import time

import kavach_business as kb
import kavach_common as kc

LANG_NAMES = {"te": "తెలుగు", "hi": "हिन्दी", "en": "English"}
LANG_BUTTONS = [("LANG|te", "తెలుగు"), ("LANG|hi", "हिन्दी"), ("LANG|en", "English")]
LANG_PROMPT = "Choose your language / భాష ఎంచుకోండి / भाषा चुनें"
AWAIT_SECONDS = 15 * 60
MAX_FAMILY = 9  # a WhatsApp list has 10 rows; one is "Add family member"

T: dict[str, dict[str, str]] = {
    # ---- menu
    "menu_body": {
        "en": "⚙️ Kavach settings. You can change these any time.\n\nIf someone is asking you for money or an OTP "
              "right now, just forward their message or send me a voice note.",
        "te": "⚙️ కవచ్ సెట్టింగ్స్. వీటిని ఎప్పుడైనా మార్చవచ్చు.\n\nఎవరైనా ఇప్పుడు డబ్బు లేదా OTP అడుగుతుంటే, "
              "వారి మెసేజ్‌ను నాకు ఫార్వర్డ్ చేయండి లేదా వాయిస్ నోట్ పంపండి.",
        "hi": "⚙️ कवच सेटिंग्स। इन्हें कभी भी बदल सकते हैं।\n\nअगर अभी कोई आपसे पैसे या OTP माँग रहा है, तो उसका "
              "मैसेज मुझे फ़ॉरवर्ड करें या वॉइस नोट भेजें।",
    },
    "greeting": {
        "en": "Namaste{name} 🙏 Kavach is on. Forward me anything that looks suspicious, or ask me to book a doctor.",
        "te": "నమస్తే{name} 🙏 కవచ్ ఆన్‌లో ఉంది. అనుమానంగా అనిపించేది ఏదైనా నాకు ఫార్వర్డ్ చేయండి, లేదా డాక్టర్ "
              "అపాయింట్‌మెంట్ అడగండి.",
        "hi": "नमस्ते{name} 🙏 कवच चालू है। जो भी संदिग्ध लगे, मुझे फ़ॉरवर्ड करें, या डॉक्टर का अपॉइंटमेंट माँगें।",
    },
    "menu_button": {"en": "Open settings", "te": "సెట్టింగ్స్ తెరవండి", "hi": "सेटिंग्स खोलें"},
    "menu_section": {"en": "Settings", "te": "సెట్టింగ్స్", "hi": "सेटिंग्स"},
    "row_lang": {"en": "Language", "te": "భాష", "hi": "भाषा"},
    "row_lang_d": {"en": "Now: {language}", "te": "ఇప్పుడు: {language}", "hi": "अभी: {language}"},
    "row_family": {"en": "Family contacts", "te": "కుటుంబ సభ్యులు", "hi": "परिवार के सदस्य"},
    "row_family_none": {"en": "No one added yet", "te": "ఇంకా ఎవరినీ చేర్చలేదు", "hi": "अभी कोई नहीं जोड़ा"},
    "row_add": {"en": "Add family member", "te": "కుటుంబ సభ్యుడిని చేర్చు", "hi": "परिवार का सदस्य जोड़ें"},
    "row_add_d": {"en": "They get an alert if you are in danger", "te": "మీకు ప్రమాదం ఉంటే వారికి హెచ్చరిక వెళ్తుంది",
                  "hi": "आप ख़तरे में हों तो उन्हें अलर्ट जाएगा"},
    "row_linked": {"en": "Linked services", "te": "లింక్ అయిన సేవలు", "hi": "जुड़ी सेवाएँ"},
    "row_linked_d": {"en": "Bank, insurer, clinic records Kavach can check",
                     "te": "కవచ్ చూడగలిగే బ్యాంక్, ఇన్సూరెన్స్, క్లినిక్ రికార్డులు",
                     "hi": "बैंक, बीमा, क्लिनिक के रिकॉर्ड जो कवच देख सकता है"},
    "row_district": {"en": "District", "te": "జిల్లా", "hi": "ज़िला"},
    "row_district_d": {"en": "Now: {d}", "te": "ఇప్పుడు: {d}", "hi": "अभी: {d}"},
    "row_district_none": {"en": "Not set: for warnings about scams near you", "te": "ఇంకా సెట్ చేయలేదు",
                          "hi": "अभी सेट नहीं"},
    "row_pause": {"en": "Pause Kavach", "te": "కవచ్‌ను ఆపు", "hi": "कवच रोकें"},
    "row_pause_d": {"en": "Stop checks and family alerts", "te": "చెకింగ్‌లు, కుటుంబ హెచ్చరికలు ఆగిపోతాయి",
                    "hi": "जाँच और परिवार अलर्ट बंद"},
    "row_resume": {"en": "Turn Kavach on", "te": "కవచ్‌ను ఆన్ చేయి", "hi": "कवच चालू करें"},
    "row_resume_d": {"en": "Kavach is paused now", "te": "కవచ్ ఇప్పుడు ఆగి ఉంది", "hi": "कवच अभी रुका है"},
    "row_how": {"en": "What Kavach can do", "te": "కవచ్ ఏం చేయగలదు", "hi": "कवच क्या कर सकता है"},
    "row_how_d": {"en": "Examples you can try", "te": "మీరు ప్రయత్నించగల ఉదాహరణలు", "hi": "आज़माने के लिए उदाहरण"},
    "how": {
        "en": "Here's what I can do:\n"
              "• Tell you if a message, link, screenshot, PDF or voice note is a scam: just forward it.\n"
              "• Alert your family at once if someone is scaring you into paying.\n"
              "• Help right away if money was already sent (a ready complaint for 1930).\n"
              "• Check messages from your bank, insurer or pharmacy against your real records, if they are "
              "Kavach members.\n"
              "• Book a doctor: \"I have fever since yesterday\".\n"
              "• Find a product on the official Amazon and Flipkart sites: \"I want to buy a pressure cooker\".",
        "te": "నేను చేయగలిగేవి:\n"
              "• మెసేజ్, లింక్, స్క్రీన్‌షాట్, PDF లేదా వాయిస్ నోట్ మోసమా కాదా చెప్పడం: నాకు ఫార్వర్డ్ చేయండి.\n"
              "• ఎవరైనా భయపెట్టి డబ్బు అడుగుతుంటే వెంటనే మీ కుటుంబానికి తెలియజేయడం.\n"
              "• డబ్బు ఇప్పటికే పంపేసి ఉంటే వెంటనే సహాయం (1930 కోసం సిద్ధమైన ఫిర్యాదు).\n"
              "• మీ బ్యాంక్, ఇన్సూరెన్స్, ఫార్మసీ కవచ్ సభ్యులైతే, వారి పేరుతో వచ్చిన మెసేజ్‌లను మీ అసలు రికార్డులతో "
              "పోల్చడం.\n"
              "• డాక్టర్ అపాయింట్‌మెంట్: \"నిన్నటి నుంచి జ్వరం ఉంది\".\n"
              "• అధికారిక Amazon, Flipkart సైట్లలో వస్తువు వెతకడం: \"నాకు ప్రెషర్ కుక్కర్ కొనాలి\".",
        "hi": "मैं ये कर सकता हूँ:\n"
              "• मैसेज, लिंक, स्क्रीनशॉट, PDF या वॉइस नोट धोखा है या नहीं, यह बताना: बस फ़ॉरवर्ड करें।\n"
              "• कोई डराकर पैसे माँगे तो तुरंत आपके परिवार को बताना।\n"
              "• पैसे भेज दिए हों तो तुरंत मदद (1930 के लिए तैयार शिकायत)।\n"
              "• आपका बैंक, बीमा या फ़ार्मेसी कवच से जुड़ा हो तो उनके नाम से आए मैसेज को आपके असली रिकॉर्ड से "
              "मिलाना।\n"
              "• डॉक्टर अपॉइंटमेंट: \"कल से बुखार है\"।\n"
              "• आधिकारिक Amazon और Flipkart पर सामान ढूँढना: \"मुझे प्रेशर कुकर खरीदना है\"।",
    },
    # ---- language
    "lang_changed": {"en": "✅ Language changed to English.", "te": "✅ భాష తెలుగుకు మార్చబడింది.",
                     "hi": "✅ भाषा हिन्दी कर दी गई।"},
    # ---- family
    "family_body": {
        "en": "These family members get a WhatsApp alert (and an email, if added) when something looks dangerous. "
              "Tap a name to remove it.",
        "te": "ప్రమాదం అనిపించినప్పుడు ఈ కుటుంబ సభ్యులకు WhatsApp హెచ్చరిక (ఈమెయిల్ ఉంటే అది కూడా) వెళ్తుంది. "
              "తొలగించాలంటే పేరును నొక్కండి.",
        "hi": "ख़तरा लगने पर परिवार के इन सदस्यों को WhatsApp अलर्ट (ईमेल हो तो वह भी) जाता है। हटाने के लिए नाम पर "
              "टैप करें।",
    },
    "family_button": {"en": "See family", "te": "కుటుంబం చూడండి", "hi": "परिवार देखें"},
    "ask_family": {
        "en": "Send your family member's contact: tap 📎 (or +), choose *Contact* and pick them.\n\n"
              "Or type their name and number, like:\nRavi 98765 43210\n"
              "(add their email after the number if they should get emails too)",
        "te": "మీ కుటుంబ సభ్యుడి కాంటాక్ట్ పంపండి: 📎 (లేదా +) నొక్కి, *Contact* ఎంచుకుని, వారిని ఎంచుకోండి.\n\n"
              "లేదా పేరు, నంబర్ ఇలా టైప్ చేయండి:\nRavi 98765 43210\n"
              "(వారికి ఈమెయిల్ కూడా కావాలంటే నంబర్ తర్వాత ఈమెయిల్ రాయండి)",
        "hi": "परिवार के सदस्य का कॉन्टैक्ट भेजें: 📎 (या +) दबाएँ, *Contact* चुनें और उन्हें चुनें।\n\n"
              "या नाम और नंबर ऐसे लिखें:\nRavi 98765 43210\n"
              "(उन्हें ईमेल भी चाहिए तो नंबर के बाद ईमेल लिखें)",
    },
    "added": {"en": "✅ {name} ({phone}) will get an alert if something looks dangerous.",
              "te": "✅ ప్రమాదం అనిపిస్తే {name} ({phone})కు హెచ్చరిక వెళ్తుంది.",
              "hi": "✅ ख़तरा लगने पर {name} ({phone}) को अलर्ट जाएगा।"},
    "email_hint": {"en": "To send them emails too, reply with their email address.",
                   "te": "వారికి ఈమెయిల్ కూడా పంపాలంటే, వారి ఈమెయిల్ అడ్రస్ పంపండి.",
                   "hi": "उन्हें ईमेल भी भेजना हो तो उनका ईमेल पता भेजें।"},
    "email_saved": {"en": "✅ Saved {email} for {name}.", "te": "✅ {name} కోసం {email} సేవ్ చేశాను.",
                    "hi": "✅ {name} के लिए {email} सेव कर दिया।"},
    "own_number": {"en": "That's your own number. Please send a family member's number.",
                   "te": "అది మీ సొంత నంబర్. దయచేసి కుటుంబ సభ్యుడి నంబర్ పంపండి.",
                   "hi": "यह आपका अपना नंबर है। कृपया परिवार के सदस्य का नंबर भेजें।"},
    "family_full": {"en": "You already have {n} family contacts. Remove one first.",
                    "te": "ఇప్పటికే {n} కుటుంబ సభ్యులు ఉన్నారు. ముందు ఒకరిని తొలగించండి.",
                    "hi": "पहले से {n} परिवार सदस्य हैं। पहले किसी एक को हटाएँ।"},
    "confirm_add": {"en": "Add {name} ({phone}) as a family contact? They will get an alert if something looks "
                          "dangerous.",
                    "te": "{name} ({phone})ను కుటుంబ సభ్యుడిగా చేర్చాలా? ప్రమాదం అనిపిస్తే వారికి హెచ్చరిక వెళ్తుంది.",
                    "hi": "{name} ({phone}) को परिवार के सदस्य के रूप में जोड़ें? ख़तरा लगने पर उन्हें अलर्ट जाएगा।"},
    "btn_add_yes": {"en": "Yes, add", "te": "అవును, చేర్చు", "hi": "हाँ, जोड़ें"},
    "btn_check": {"en": "Check this number", "te": "నంబర్ చెక్ చేయి", "hi": "नंबर जाँचें"},
    "btn_no": {"en": "No", "te": "వద్దు", "hi": "नहीं"},
    "remove_q": {"en": "Remove {name} ({phone}) from family alerts?",
                 "te": "{name} ({phone})ను కుటుంబ హెచ్చరికల నుంచి తొలగించాలా?",
                 "hi": "{name} ({phone}) को परिवार अलर्ट से हटाएँ?"},
    "btn_remove": {"en": "Remove", "te": "తొలగించు", "hi": "हटाएँ"},
    "btn_keep": {"en": "Keep", "te": "ఉంచు", "hi": "रहने दें"},
    "removed": {"en": "✅ {name} removed.", "te": "✅ {name}ను తొలగించాను.", "hi": "✅ {name} को हटा दिया।"},
    "none_left": {"en": "No family member will be alerted now. Send MENU to add one.",
                  "te": "ఇప్పుడు ఏ కుటుంబ సభ్యుడికీ హెచ్చరిక వెళ్లదు. చేర్చడానికి MENU పంపండి.",
                  "hi": "अब परिवार में किसी को अलर्ट नहीं जाएगा। जोड़ने के लिए MENU भेजें।"},
    "no_change": {"en": "OK, no change.", "te": "సరే, ఏ మార్పూ లేదు.", "hi": "ठीक है, कोई बदलाव नहीं।"},
    # ---- pause / resume
    "paused": {"en": "⏸️ Kavach is paused. I won't check messages or alert your family until you turn me back on.",
               "te": "⏸️ కవచ్ ఆగింది. మళ్ళీ ఆన్ చేసే వరకు నేను మెసేజ్‌లు చెక్ చేయను, మీ కుటుంబానికి హెచ్చరికలు పంపను.",
               "hi": "⏸️ कवच रुक गया है। दोबारा चालू करने तक मैं मैसेज नहीं जाँचूँगा और परिवार को अलर्ट नहीं भेजूँगा।"},
    "paused_nudge": {"en": "Kavach is paused, so I didn't check this. Turn Kavach on to check it.",
                     "te": "కవచ్ ఆగి ఉంది, కాబట్టి ఇది చెక్ చేయలేదు. చెక్ చేయాలంటే కవచ్‌ను ఆన్ చేయండి.",
                     "hi": "कवच रुका हुआ है, इसलिए यह नहीं जाँचा। जाँचने के लिए कवच चालू करें।"},
    "btn_resume": {"en": "Turn Kavach on", "te": "కవచ్ ఆన్ చేయి", "hi": "कवच चालू करें"},
    "resumed": {"en": "▶️ Kavach is on again. Forward me anything that looks suspicious.",
                "te": "▶️ కవచ్ మళ్ళీ ఆన్ అయింది. అనుమానంగా అనిపించేది ఏదైనా నాకు ఫార్వర్డ్ చేయండి.",
                "hi": "▶️ कवच फिर से चालू है। जो भी संदिग्ध लगे, मुझे फ़ॉरवर्ड करें।"},
    "pause_q": {"en": "Pause Kavach? I won't check messages or alert your family until you turn it on again.",
                "te": "కవచ్‌ను ఆపాలా? మళ్ళీ ఆన్ చేసే వరకు నేను మెసేజ్‌లు చెక్ చేయను, మీ కుటుంబానికి హెచ్చరికలు పంపను.",
                "hi": "कवच रोकें? दोबारा चालू करने तक मैं मैसेज नहीं जाँचूँगा और परिवार को अलर्ट नहीं भेजूँगा।"},
    "btn_pause": {"en": "Pause", "te": "ఆపు", "hi": "रोकें"},
    "btn_keep_on": {"en": "Keep it on", "te": "ఆన్‌లోనే ఉంచు", "hi": "चालू रखें"},
    # ---- district and bank
    "district_q": {"en": "Which district do you live in? Type its name, for example: Kurnool",
                   "te": "మీరు ఏ జిల్లాలో ఉంటారు? పేరు టైప్ చేయండి, ఉదాహరణకు: Kurnool",
                   "hi": "आप किस ज़िले में रहते हैं? नाम लिखें, जैसे: Kurnool"},
    "district_saved": {"en": "✅ District saved: {d}. You'll get warnings about scam waves near you.",
                       "te": "✅ జిల్లా సేవ్ అయింది: {d}. మీ దగ్గర జరుగుతున్న మోసాల గురించి హెచ్చరికలు వస్తాయి.",
                       "hi": "✅ ज़िला सेव हो गया: {d}। आपके आसपास चल रहे धोखों की चेतावनी मिलेगी।"},
    "bank_saved": {"en": "✅ Bank saved: {b}.", "te": "✅ బ్యాంక్ సేవ్ అయింది: {b}.", "hi": "✅ बैंक सेव हो गया: {b}।"},
    # ---- linked services
    "linked_body": {
        "en": "These services joined Kavach and linked your record using the mobile number registered with them "
              "(this WhatsApp number). Kavach checks messages that claim to be from them against your real record. "
              "Tap one to see what it shares, or to unlink it.",
        "te": "ఈ సేవలు కవచ్‌లో చేరి, వారి దగ్గర నమోదైన మీ మొబైల్ నంబర్ (ఈ WhatsApp నంబరే) ద్వారా మీ రికార్డును "
              "లింక్ చేశాయి. వారి పేరుతో వచ్చే మెసేజ్‌లను కవచ్ మీ అసలు రికార్డుతో పోలుస్తుంది. ఏమి పంచుకుంటారో "
              "చూడటానికి లేదా అన్‌లింక్ చేయడానికి ఒకదాన్ని నొక్కండి.",
        "hi": "ये सेवाएँ कवच से जुड़ी हैं और इनके पास दर्ज आपके मोबाइल नंबर (यही WhatsApp नंबर) से आपका रिकॉर्ड "
              "जोड़ा गया है। इनके नाम से आए मैसेज को कवच आपके असली रिकॉर्ड से मिलाता है। क्या साझा होता है देखने या "
              "अनलिंक करने के लिए किसी पर टैप करें।",
    },
    "linked_button": {"en": "See services", "te": "సేవలు చూడండి", "hi": "सेवाएँ देखें"},
    "linked_row_d": {"en": "Linked {date} via {channel}", "te": "{date}న {channel} ద్వారా లింక్",
                     "hi": "{date} को {channel} से जुड़ा"},
    "no_linked": {
        "en": "No services are linked to your number yet. When your bank, insurer, pharmacy or clinic joins Kavach, "
              "you can link your record from their app or counter.",
        "te": "మీ నంబర్‌కు ఇంకా ఏ సేవా లింక్ కాలేదు. మీ బ్యాంక్, ఇన్సూరెన్స్, ఫార్మసీ లేదా క్లినిక్ కవచ్‌లో చేరినప్పుడు, "
              "వారి యాప్ లేదా కౌంటర్‌లో మీ రికార్డును లింక్ చేయవచ్చు.",
        "hi": "आपके नंबर से अभी कोई सेवा नहीं जुड़ी है। जब आपका बैंक, बीमा, फ़ार्मेसी या क्लिनिक कवच से जुड़े, तो आप "
              "उनके ऐप या काउंटर से अपना रिकॉर्ड जोड़ सकते हैं।",
    },
    "biz_detail": {
        "en": "*{name}*\nLinked: {date}, via {channel}\nKavach can see: {shares}\n\nKavach never sees your passwords, "
              "PINs or OTPs. {short} gets a scam message from Kavach only if you tap Report.",
        "te": "*{name}*\nలింక్: {date}, {channel} ద్వారా\nకవచ్ చూడగలిగేది: {shares}\n\nమీ పాస్‌వర్డ్‌లు, PINలు, "
              "OTPలు కవచ్ ఎప్పుడూ చూడదు. మీరు రిపోర్ట్ నొక్కితేనే మోసం మెసేజ్ {short}కు వెళ్తుంది.",
        "hi": "*{name}*\nजुड़ा: {date}, {channel} से\nकवच देख सकता है: {shares}\n\nकवच आपके पासवर्ड, PIN या OTP "
              "कभी नहीं देखता। आप रिपोर्ट दबाएँ, तभी धोखे वाला मैसेज {short} को जाता है।",
    },
    "via_booking": {"en": "your first booking through Kavach", "te": "కవచ్ ద్వారా మీ మొదటి బుకింగ్",
                    "hi": "कवच से आपकी पहली बुकिंग"},
    "btn_unlink": {"en": "Unlink", "te": "అన్‌లింక్", "hi": "अनलिंक करें"},
    "unlinked": {"en": "✅ Unlinked. Kavach no longer sees your {name} record. You can link it again from {channel}.",
                 "te": "✅ అన్‌లింక్ అయింది. మీ {name} రికార్డును కవచ్ ఇక చూడదు. మళ్ళీ లింక్ చేయాలంటే {channel}లో "
                       "చేయవచ్చు.",
                 "hi": "✅ अनलिंक हो गया। कवच अब आपका {name} रिकॉर्ड नहीं देखेगा। दोबारा जोड़ना हो तो {channel} से "
                       "जोड़ सकते हैं।"},
    "expired": {"en": "That option has expired. Send MENU to see your settings.",
                "te": "ఆ ఆప్షన్ గడువు ముగిసింది. సెట్టింగ్స్ చూడటానికి MENU పంపండి.",
                "hi": "यह विकल्प पुराना हो गया। सेटिंग्स देखने के लिए MENU भेजें।"},
    # ---- welcome after consent
    "welcome": {
        "en": "You're protected. 🛡️ Forward me anything that looks suspicious: a message, link, screenshot, PDF or "
              "voice note.\n\nAdd a family member who should be alerted if you are in danger. Send MENU any time to "
              "change your language or family contacts, or to pause Kavach.",
        "te": "మీకు రక్షణ ప్రారంభమైంది. 🛡️ అనుమానంగా అనిపించే ఏదైనా నాకు ఫార్వర్డ్ చేయండి: మెసేజ్, లింక్, "
              "స్క్రీన్‌షాట్, PDF లేదా వాయిస్ నోట్.\n\nమీకు ప్రమాదం ఉంటే హెచ్చరిక అందుకోవాల్సిన కుటుంబ సభ్యుడిని "
              "చేర్చండి. భాష, కుటుంబ సభ్యులను మార్చడానికి లేదా కవచ్‌ను ఆపడానికి ఎప్పుడైనా MENU అని పంపండి.",
        "hi": "आप सुरक्षित हैं। 🛡️ जो भी संदिग्ध लगे, मुझे फ़ॉरवर्ड करें: मैसेज, लिंक, स्क्रीनशॉट, PDF या वॉइस नोट।"
              "\n\nख़तरे में अलर्ट पाने वाले परिवार के सदस्य को जोड़ें। भाषा या परिवार बदलने, या कवच रोकने के लिए कभी "
              "भी MENU भेजें।",
    },
    "thanks": {"en": "🙏 Anytime. Forward me anything that looks suspicious.",
               "te": "🙏 ఎప్పుడైనా సరే. అనుమానంగా అనిపించేది ఏదైనా నాకు ఫార్వర్డ్ చేయండి.",
               "hi": "🙏 कभी भी। जो भी संदिग्ध लगे, मुझे फ़ॉरवर्ड करें।"},
    "btn_add_family": {"en": "Add family member", "te": "కుటుంబాన్ని చేర్చు", "hi": "परिवार जोड़ें"},
    "btn_settings": {"en": "Settings", "te": "సెట్టింగ్స్", "hi": "सेटिंग्स"},
}


def _t(key: str, lang: str | None, **kw) -> str:
    texts = T[key]
    text = texts.get(lang or "en") or texts["en"]
    return text.format(**kw) if kw else text


def _lang(user: dict) -> str:
    lang = (user or {}).get("language")
    return lang if lang in LANG_NAMES else "en"


def pretty_phone(phone: str) -> str:
    d = kc.phone_digits(phone)
    return f"+91 {d[2:7]} {d[7:]}" if len(d) == 12 and d.startswith("91") else ("+" + d if d else "")


# =========================================================================== recognising short requests

def _norm(text: str) -> str:
    """Lower-case and drop punctuation, keeping Telugu and Hindi vowel signs intact."""
    text = re.sub(r"[!?.,;:\"'()\[\]{}।|*_~]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


PHRASES: dict[str, set[str]] = {
    "menu": {"menu", "settings", "setting", "options", "option", "మెనూ", "మెను", "సెట్టింగ్స్", "సెట్టింగులు",
             "मेनू", "सेटिंग", "सेटिंग्स", "विकल्प"},
    "greet": {"hi", "hii", "hiii", "hello", "helo", "hey", "namaste", "namaskar", "namaskaram", "start",
              "హాయ్", "హలో", "నమస్తే", "నమస్కారం", "నమస్కారాలు", "नमस्ते", "नमस्कार", "हाय", "हेलो", "हैलो"},
    "language": {"language", "lang", "change language", "change my language", "languages", "భాష", "భాష మార్చు",
                 "భాష మార్చండి", "భాష మార్చాలి", "भाषा", "भाषा बदलें", "भाषा बदलो", "भाषा बदलना है"},
    "family": {"guardian", "guardians", "family", "family contacts", "family members", "my family", "change guardian",
               "remove guardian", "edit guardian", "change family", "remove family", "కుటుంబం", "కుటుంబ సభ్యులు",
               "గార్డియన్", "గార్డియన్ మార్చు", "परिवार", "परिवार के सदस्य", "गार्डियन", "गार्डियन बदलें"},
    "add_family": {"add guardian", "add family", "add family member", "add a family member", "new guardian",
                   "add contact", "add member", "కుటుంబ సభ్యుడిని చేర్చు", "గార్డియన్ చేర్చు", "కుటుంబాన్ని చేర్చు",
                   "परिवार जोड़ें", "गार्डियन जोड़ें", "परिवार का सदस्य जोड़ें"},
    "pause": {"stop", "pause", "unsubscribe", "stop kavach", "pause kavach", "ఆపు", "ఆపండి", "ఆపేయి", "కవచ్ ఆపు",
              "रोको", "रोकें", "बंद", "बंद करो", "बंद करें", "कवच रोकें"},
    "resume": {"resume", "restart", "start again", "turn on", "start kavach", "turn kavach on", "ప్రారంభించు",
               "మళ్ళీ ప్రారంభించు", "ఆన్ చేయి", "కవచ్ ఆన్ చేయి", "चालू", "चालू करें", "शुरू", "शुरू करें",
               "कवच चालू करें"},
    "linked": {"linked", "linked services", "my services", "my accounts", "my data", "privacy", "లింక్ అయిన సేవలు",
               "నా డేటా", "जुड़ी सेवाएँ", "मेरा डेटा"},
    "thanks": {"thanks", "thank you", "thankyou", "thanks a lot", "ok", "okay", "ok thanks", "ok thank you", "👍", "🙏",
               "ధన్యవాదాలు", "థాంక్స్", "థాంక్యూ", "సరే", "సరే ధన్యవాదాలు", "धन्यवाद", "शुक्रिया", "ठीक है", "ओके"},
    "how": {"what can you do", "what can kavach do", "how to use", "how to use kavach", "examples", "కవచ్ ఏం చేయగలదు",
            "ఏం చేయగలవు", "कवच क्या कर सकता है", "क्या कर सकते हो"},
}
LANG_DIRECT = {"english": "en", "in english": "en", "english please": "en", "ఇంగ్లీష్": "en", "अंग्रेज़ी": "en",
               "अंग्रेजी": "en", "telugu": "te", "in telugu": "te", "telugu lo": "te", "తెలుగు": "te",
               "తెలుగులో": "te", "तेलुगु": "te", "hindi": "hi", "in hindi": "hi", "hindi mein": "hi", "హిందీ": "hi",
               "हिंदी": "hi", "हिन्दी": "hi", "हिंदी में": "hi"}
ADD_WORDS = re.compile(r"\badd\b|జోడించ|చేర్చ|जोड़", re.I)  # an explicit "add", not just "family"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d\s-]{8,}\d")
FILLER = {"add", "please", "pls", "as", "a", "an", "my", "guardian", "family", "member", "contact", "number", "to",
          "new", "and", "for", "alerts", "is", "guardian:", "జోడించు", "జోడించండి", "చేర్చు", "చేర్చండి",
          "గార్డియన్", "కుటుంబ", "సభ్యుడు", "సభ్యుడిగా", "నంబర్", "నా", "जोड़ें", "जोड़ो", "गार्डियन", "परिवार",
          "सदस्य", "नंबर", "को", "का", "के", "मेरा", "मेरी", "मेरे", "में"}


def intent(text: str | None, forwarded: bool = False) -> tuple[str, str] | None:
    """What a short message typed by the person asks for, or None if it is something to check.

    Forwarded messages are never settings requests: they are someone else's words.
    """
    if forwarded or not text or not text.strip():
        return None
    raw = text.strip()
    upper = raw.upper()
    for cmd in ("GUARDIAN", "DISTRICT", "BANK"):
        if upper == cmd or upper.startswith(cmd + " ") or upper.startswith(cmd + ":"):
            arg = raw[len(cmd):].lstrip(" :").strip()
            if cmd == "GUARDIAN":
                return ("guardian_cmd", arg) if arg else ("family", "")
            if cmd == "DISTRICT":
                return ("district", arg) if arg else ("district_ask", "")
            return ("bank", arg) if arg else ("menu", "")
    n = _norm(raw)
    if n in LANG_DIRECT:
        return "set_language", LANG_DIRECT[n]
    for kind, phrases in PHRASES.items():
        if n in phrases:
            return kind, ""
    if len(n.split()) <= 12 and PHONE_RE.search(raw) and ADD_WORDS.search(raw):
        return "add_with_number", raw
    return None


def parse_contact_text(text: str) -> dict | None:
    """{"name", "phone", "email"} from "Ravi 98765 43210 ravi@x.com" or "add my son Ravi +91 98765 43210"."""
    text = text or ""
    email_match = EMAIL_RE.search(text)
    email = email_match.group(0).lower() if email_match else ""
    rest = text.replace(email_match.group(0), " ") if email_match else text
    phone_match = PHONE_RE.search(rest)
    if not phone_match:
        return None
    digits = kc.phone_digits(phone_match.group(0))
    if not 10 <= len(digits) <= 15:
        return None
    words = (rest[:phone_match.start()] + " " + rest[phone_match.end():]).split()
    name = " ".join(w for w in words if w.lower().strip(",.:;") not in FILLER).strip(" ,.:;-")
    return {"name": name[:40] or "Family", "phone": kc.normalize_phone(phone_match.group(0)), "email": email}


def contact_from_card(contacts: list | None) -> dict | None:
    """The first contact with a phone number from a WhatsApp contacts message."""
    for c in contacts or []:
        n = c.get("name") or {}
        name = n.get("formatted_name") or " ".join(x for x in (n.get("first_name"), n.get("last_name")) if x)
        for ph in c.get("phones") or []:
            number = ph.get("wa_id") or ph.get("phone") or ""
            if 10 <= len(kc.phone_digits(number)) <= 15:
                emails = [e.get("email", "") for e in c.get("emails") or [] if e.get("email")]
                return {"name": (name or "Family")[:40], "phone": kc.normalize_phone(number),
                        "email": (emails[0] if emails else "").lower()}
    return None


# =========================================================================== building the lists

def _family_names(user: dict) -> str:
    return ", ".join(g.get("name") or pretty_phone(g.get("phone", "")) for g in user.get("guardians", []))


def menu_list(user: dict, greet: bool = False) -> dict:
    lang = _lang(user)
    paused = user.get("status") == "stopped"
    first = (user.get("name") or "").split()
    body = (_t("greeting", lang, name=(" " + first[0]) if first else "") + "\n\n" if greet and not paused else "")
    body += _t("menu_body", lang)
    rows = [
        {"id": "SET|lang", "title": _t("row_lang", lang), "description": _t("row_lang_d", lang, language=LANG_NAMES[lang])},
        {"id": "SET|family", "title": _t("row_family", lang),
         "description": _family_names(user) or _t("row_family_none", lang)},
        {"id": "SET|add", "title": _t("row_add", lang), "description": _t("row_add_d", lang)},
        {"id": "SET|linked", "title": _t("row_linked", lang), "description": _t("row_linked_d", lang)},
        {"id": "SET|district", "title": _t("row_district", lang),
         "description": _t("row_district_d", lang, d=user["district"]) if user.get("district")
         else _t("row_district_none", lang)},
        {"id": "SET|resume", "title": _t("row_resume", lang), "description": _t("row_resume_d", lang)} if paused else
        {"id": "SET|pause", "title": _t("row_pause", lang), "description": _t("row_pause_d", lang)},
        {"id": "SET|how", "title": _t("row_how", lang), "description": _t("row_how_d", lang)},
    ]
    return {"body": body, "button": _t("menu_button", lang), "header": "Kavach",
            "sections": [{"title": _t("menu_section", lang), "rows": rows}]}


def language_list() -> dict:
    return {"body": LANG_PROMPT, "button": "భాష / भाषा / Language", "header": None,
            "sections": [{"title": "Language", "rows": [{"id": bid, "title": title, "description": ""}
                                                       for bid, title in LANG_BUTTONS]}]}


def family_list(user: dict) -> dict:
    lang = _lang(user)
    rows = [{"id": f"SET|g|{kc.phone_digits(g.get('phone', ''))}", "title": (g.get("name") or "Family")[:24],
             "description": " · ".join(x for x in (pretty_phone(g.get("phone", "")), g.get("email", "")) if x)}
            for g in user.get("guardians", [])[:MAX_FAMILY]]
    rows.append({"id": "SET|add", "title": "➕ " + _t("row_add", lang)[:22], "description": _t("row_add_d", lang)})
    return {"body": _t("family_body", lang), "button": _t("family_button", lang), "header": None,
            "sections": [{"title": _t("row_family", lang), "rows": rows}]}


def linked_records(phone: str) -> list[tuple[str, dict]]:
    out = []
    for business_id in kb.PROFILES:
        try:
            record = kb.get_record(business_id, phone)
        except Exception as exc:
            print(f"Linked record lookup failed for {business_id}: {exc!r}")
            record = None
        if record:
            out.append((business_id, record))
    return out


def _channel(business_id: str, record: dict, lang: str) -> str:
    if record.get("linked_via") == "kavach_booking":
        return _t("via_booking", lang)
    ch = kb.PROFILES[business_id].get("link_channel") or {}
    return ch.get(lang) or ch.get("en") or kb.PROFILES[business_id]["name"]


def _linked_date(record: dict) -> str:
    return kb.human_date(record.get("linked_at") or str(record.get("updated_at", ""))[:10])


def linked_list(user: dict) -> dict | None:
    lang = _lang(user)
    found = linked_records(user.get("phone", ""))
    if not found:
        return None
    rows = [{"id": f"SET|biz|{bid}", "title": kb.PROFILES[bid]["name"][:24],
             "description": _t("linked_row_d", lang, date=_linked_date(rec), channel=_channel(bid, rec, lang))}
            for bid, rec in found[:10]]
    return {"body": _t("linked_body", lang), "button": _t("linked_button", lang), "header": None,
            "sections": [{"title": _t("row_linked", lang), "rows": rows}]}


# =========================================================================== sending

def _send_list(phone: str, lst: dict) -> None:
    kc.wa_list(phone, lst["body"], lst["button"], lst["sections"], header=lst.get("header"))


def send_menu(user: dict, greet: bool = False) -> None:
    _send_list(user["phone"], menu_list(user, greet))


def send_language_buttons(phone: str) -> None:
    kc.wa_buttons(phone, LANG_PROMPT, LANG_BUTTONS)


def send_welcome(user: dict) -> None:
    lang = _lang(user)
    kc.wa_buttons(user["phone"], _t("welcome", lang),
                  [("SET|add", _t("btn_add_family", lang)), ("SET|menu", _t("btn_settings", lang))])


def send_paused_nudge(user: dict) -> None:
    lang = _lang(user)
    kc.wa_buttons(user["phone"], _t("paused_nudge", lang), [("SET|resume", _t("btn_resume", lang))])


# =========================================================================== changes

def _save(user: dict) -> None:
    kc.put_user(user)


def _until() -> int:
    return int(time.time()) + AWAIT_SECONDS


def _live(item: dict | None) -> dict | None:
    return item if item and int(item.get("until", 0)) >= time.time() else None


def set_language(user: dict, lang: str, show_menu: bool = False) -> None:
    """Switch language. After a tap, the menu is sent again in the new language, so an old menu in the
    previous language isn't the one left on screen."""
    user["language"] = lang if lang in LANG_NAMES else "en"
    _save(user)
    done = _t("lang_changed", user["language"])
    if show_menu:
        lst = menu_list(user)
        lst["body"] = done + "\n\n" + lst["body"]
        _send_list(user["phone"], lst)
    else:
        kc.wa_text(user["phone"], done)


def pause(user: dict) -> None:
    user["status"] = "stopped"
    user["paused_at"] = kc.now_iso()
    user.pop("awaiting", None)
    _save(user)
    kc.wa_buttons(user["phone"], _t("paused", _lang(user)), [("SET|resume", _t("btn_resume", _lang(user)))])


def resume(user: dict) -> None:
    user["status"] = "active"
    user.setdefault("consent_at", kc.now_iso())
    _save(user)
    kc.wa_text(user["phone"], _t("resumed", _lang(user)))


def ask_family(user: dict) -> None:
    lang = _lang(user)
    if len(user.get("guardians", [])) >= MAX_FAMILY:
        kc.wa_text(user["phone"], _t("family_full", lang, n=MAX_FAMILY))
        return
    user["awaiting"] = {"what": "guardian", "until": _until()}
    _save(user)
    kc.wa_text(user["phone"], _t("ask_family", lang))


def add_guardian(user: dict, guardian: dict) -> None:
    """Add (or update) a family contact the person gave themselves, and offer to add an email."""
    lang = _lang(user)
    phone = kc.normalize_phone(guardian["phone"])
    if phone == kc.normalize_phone(user["phone"]):
        kc.wa_text(user["phone"], _t("own_number", lang))
        return
    others = [g for g in user.get("guardians", []) if kc.normalize_phone(g.get("phone", "")) != phone]
    if len(others) >= MAX_FAMILY:
        kc.wa_text(user["phone"], _t("family_full", lang, n=MAX_FAMILY))
        return
    old = next((g for g in user.get("guardians", []) if kc.normalize_phone(g.get("phone", "")) == phone), {})
    g = {"name": (guardian.get("name") or old.get("name") or "Family").strip()[:40], "phone": phone,
         "email": (guardian.get("email") or old.get("email") or "").lower()}
    user["guardians"] = others + [g]
    user.pop("pending_guardian", None)
    text = _t("added", lang, name=g["name"], phone=pretty_phone(phone))
    if g["email"]:
        user.pop("awaiting", None)
    else:
        user["awaiting"] = {"what": "guardian_email", "phone": phone, "until": _until()}
        text += "\n" + _t("email_hint", lang)
    _save(user)
    kc.wa_text(user["phone"], text)


def propose_guardian(user: dict, guardian: dict, offer_check: bool = False) -> None:
    """Ask before adding a contact Kavach inferred (a shared contact card, or "add Ravi 98765 43210")."""
    lang = _lang(user)
    phone = kc.normalize_phone(guardian["phone"])
    if phone == kc.normalize_phone(user["phone"]):
        kc.wa_text(user["phone"], _t("own_number", lang))
        return
    user["pending_guardian"] = {**guardian, "phone": phone, "until": _until()}
    _save(user)
    buttons = [("SET|addyes", _t("btn_add_yes", lang))]
    if offer_check:
        buttons.append(("SET|checknum", _t("btn_check", lang)))
    buttons.append(("SET|addno", _t("btn_no", lang)))
    kc.wa_buttons(user["phone"], _t("confirm_add", lang, name=guardian.get("name") or "Family",
                                     phone=pretty_phone(phone)), buttons)


def send_family(user: dict) -> None:
    if not user.get("guardians"):
        ask_family(user)
        return
    _send_list(user["phone"], family_list(user))


def send_linked(user: dict) -> None:
    lst = linked_list(user)
    if lst:
        _send_list(user["phone"], lst)
    else:
        kc.wa_text(user["phone"], _t("no_linked", _lang(user)))


def ask_district(user: dict) -> None:
    user["awaiting"] = {"what": "district", "until": _until()}
    _save(user)
    kc.wa_text(user["phone"], _t("district_q", _lang(user)))


def save_district(user: dict, name: str) -> None:
    user["district"] = re.sub(r"\s+", " ", name).strip().title()[:40]
    user.pop("awaiting", None)
    _save(user)
    kc.wa_text(user["phone"], _t("district_saved", _lang(user), d=user["district"]))


# =========================================================================== entry points (inbound Lambda)

def handle_text(user: dict, text: str, forwarded: bool = False) -> bool:
    """A typed settings request from a person who has already agreed (active or paused). True if handled."""
    if not user or user.get("status") not in ("active", "stopped"):
        return False
    found = intent(text, forwarded)
    if not found:
        return False
    kind, arg = found
    lang = _lang(user)
    paused = user.get("status") == "stopped"
    if kind in ("menu",) or (kind in ("greet", "resume") and not paused):
        user.pop("awaiting", None)
        send_menu(user, greet=kind == "greet")
    elif kind in ("greet", "resume"):
        resume(user)
    elif kind == "pause":
        pause(user) if not paused else kc.wa_buttons(user["phone"], _t("paused", lang),
                                                     [("SET|resume", _t("btn_resume", lang))])
    elif kind == "language":
        send_language_buttons(user["phone"])
    elif kind == "set_language":
        set_language(user, arg)
    elif kind == "family":
        send_family(user)
    elif kind == "add_family":
        ask_family(user)
    elif kind == "guardian_cmd":
        g = parse_contact_text(arg)
        add_guardian(user, g) if g else ask_family(user)
    elif kind == "add_with_number":
        g = parse_contact_text(arg)
        waiting = _live(user.get("awaiting")) or {}
        if not g:
            ask_family(user)
        elif waiting.get("what") == "guardian":  # Kavach just asked for this
            add_guardian(user, g)
        else:
            propose_guardian(user, g)
    elif kind == "linked":
        send_linked(user)
    elif kind == "district":
        save_district(user, arg)
    elif kind == "district_ask":
        ask_district(user)
    elif kind == "bank":
        user["bank"] = arg.strip()[:40]
        _save(user)
        kc.wa_text(user["phone"], _t("bank_saved", lang, b=user["bank"]))
    elif kind == "how":
        kc.wa_text(user["phone"], _t("how", lang))
    elif kind == "thanks":
        kc.wa_text(user["phone"], _t("thanks", lang))
    else:
        return False
    return True


def handle_awaiting(user: dict, text: str, forwarded: bool = False) -> bool:
    """The answer to a question Kavach just asked (a family member's number, their email, the district)."""
    waiting = _live(user.get("awaiting"))
    if not waiting or forwarded or not text:
        if user.get("awaiting") and not waiting:
            user.pop("awaiting", None)
        return False
    what = waiting.get("what")
    if what == "guardian":
        g = parse_contact_text(text)
        if g:
            add_guardian(user, g)
            return True
    elif what == "guardian_email":
        m = EMAIL_RE.search(text)
        if m and len(text.split()) <= 4:
            target = kc.normalize_phone(waiting.get("phone", ""))
            for g in user.get("guardians", []):
                if kc.normalize_phone(g.get("phone", "")) == target:
                    g["email"] = m.group(0).lower()
                    user.pop("awaiting", None)
                    _save(user)
                    kc.wa_text(user["phone"], _t("email_saved", _lang(user), email=g["email"], name=g.get("name", "")))
                    return True
    elif what == "district":
        if len(text.split()) <= 4 and not re.search(r"\d|https?:|www\.", text):
            save_district(user, text)
            return True
    user.pop("awaiting", None)  # they moved on: treat the message normally
    _save(user)
    return False


def handle_contacts(user: dict, contacts: list | None) -> bool:
    """A contact card shared from the phone book: add it if Kavach just asked for one, otherwise ask first."""
    g = contact_from_card(contacts)
    if not g or not user or user.get("status") not in ("active", "stopped"):
        return False
    waiting = _live(user.get("awaiting"))
    if waiting and waiting.get("what") == "guardian":
        add_guardian(user, g)
    else:
        propose_guardian(user, g, offer_check=True)
    return True


def handle_tap(user: dict, choice: str) -> dict:
    """SET|... taps. Returns {"check": prompt} when the person asked Kavach to check a shared number."""
    parts = choice.split("|")
    action, arg = parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else ""
    lang = _lang(user)
    phone = user["phone"]
    if action == "menu":
        send_menu(user)
    elif action == "lang":
        send_language_buttons(phone)
    elif action == "family":
        send_family(user)
    elif action == "add":
        ask_family(user)
    elif action == "linked":
        send_linked(user)
    elif action == "district":
        ask_district(user)
    elif action == "pause":
        pause(user)
    elif action == "resume":
        resume(user)
    elif action == "how":
        kc.wa_text(phone, _t("how", lang))
    elif action == "g":  # a family member's row: confirm before removing
        g = next((g for g in user.get("guardians", []) if kc.phone_digits(g.get("phone", "")) == arg), None)
        if not g:
            kc.wa_text(phone, _t("expired", lang))
        else:
            kc.wa_buttons(phone, _t("remove_q", lang, name=g.get("name", ""), phone=pretty_phone(g["phone"])),
                          [(f"SET|rm|{arg}", _t("btn_remove", lang)), ("SET|keep", _t("btn_keep", lang))])
    elif action == "rm":
        g = next((g for g in user.get("guardians", []) if kc.phone_digits(g.get("phone", "")) == arg), None)
        if not g:
            kc.wa_text(phone, _t("expired", lang))
        else:
            user["guardians"] = [x for x in user.get("guardians", []) if x is not g]
            _save(user)
            kc.wa_text(phone, _t("removed", lang, name=g.get("name", "")) + (
                "" if user["guardians"] else "\n" + _t("none_left", lang)))
    elif action == "keep":
        kc.wa_text(phone, _t("no_change", lang))
    elif action in ("addyes", "addno", "checknum"):
        pending = _live(user.get("pending_guardian"))
        if not pending:
            kc.wa_text(phone, _t("expired", lang))
        elif action == "addyes":
            add_guardian(user, pending)
        else:
            user.pop("pending_guardian", None)
            _save(user)
            if action == "checknum":
                return {"check": f"The user shared a contact card and wants to know if this number is safe: "
                                 f"{pending.get('name', '')} {pending['phone']}"}
            kc.wa_text(phone, _t("no_change", lang))
    elif action == "biz":
        rec = kb.get_record(arg, phone) if arg in kb.PROFILES else None
        if not rec:
            kc.wa_text(phone, _t("expired", lang))
        else:
            p = kb.PROFILES[arg]
            shares = (p.get("shares_with_kavach") or {}).get(lang) or (p.get("shares_with_kavach") or {}).get("en", "")
            kc.wa_buttons(phone, _t("biz_detail", lang, name=p["name"], short=p.get("short_name", p["name"]),
                                    date=_linked_date(rec), channel=_channel(arg, rec, lang), shares=shares),
                          [(f"SET|unlink|{arg}", _t("btn_unlink", lang)), ("SET|keep", _t("btn_keep", lang))])
    elif action == "unlink":
        rec = kb.get_record(arg, phone) if arg in kb.PROFILES else None
        if not rec:
            kc.wa_text(phone, _t("expired", lang))
        else:
            kc.table("business_records_table").delete_item(Key={"business_id": arg, "phone": kc.normalize_phone(phone)})
            try:  # an anonymous count for the business: one customer unlinked
                kb.record_signal(arg, "unlinked", is_customer=True, language=lang)
            except Exception as exc:
                print(f"Unlink signal not recorded: {exc!r}")
            kc.wa_text(phone, _t("unlinked", lang, name=kb.PROFILES[arg]["name"], channel=_channel(arg, rec, lang)))
    else:
        kc.wa_text(phone, _t("expired", lang))
    return {}


# =========================================================================== for the agent (tools/settings.py)

def remember_pending_guardian(phone: str, guardian: dict) -> dict:
    """Store a family contact the agent heard about, waiting for the person's own Yes tap."""
    pending = {"name": (guardian.get("name") or "Family")[:40], "phone": kc.normalize_phone(guardian["phone"]),
               "email": (guardian.get("email") or "").lower(), "until": _until()}
    kc.table("users_table").update_item(
        Key={"phone": kc.normalize_phone(phone)},
        UpdateExpression="SET pending_guardian = :g",
        ExpressionAttributeValues={":g": kc.clean_for_dynamo(pending)},
    )
    return pending


def confirm_add_buttons(user: dict, pending: dict) -> tuple[str, list[dict]]:
    lang = _lang(user)
    return (_t("confirm_add", lang, name=pending["name"], phone=pretty_phone(pending["phone"])),
            [{"id": "SET|addyes", "title": _t("btn_add_yes", lang)}, {"id": "SET|addno", "title": _t("btn_no", lang)}])


def pause_buttons(user: dict) -> tuple[str, list[dict]]:
    lang = _lang(user)
    return (_t("pause_q", lang), [{"id": "SET|pause", "title": _t("btn_pause", lang)},
                                  {"id": "SET|keep", "title": _t("btn_keep_on", lang)}])
