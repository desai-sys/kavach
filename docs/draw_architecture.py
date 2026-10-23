#!/usr/bin/env python3
"""Draw docs/architecture.svg and docs/architecture.png.

    pip install cairosvg pillow   # pillow only for the text-fit check
    python docs/draw_architecture.py

Every text line is measured with the Inter font and the script fails if a line overflows its box.
"""
from __future__ import annotations

import sys
from html import escape
from pathlib import Path

W, H = 1760, 960
FONT = "Inter, 'Segoe UI', 'DejaVu Sans', Arial, Helvetica, sans-serif"
OUT = Path(__file__).resolve().parent

INK, MUTED, SOFT = "#1c1917", "#44403c", "#78716c"
GREY, AMBER = "#57534e", "#b45309"
STYLES = {
    "person":   ("#ffffff", GREY, False),
    "amma":     ("#fef3c7", AMBER, False),
    "business": ("#fff7ed", AMBER, False),
    "whatsapp": ("#ecfdf5", "#15803d", False),
    "ses":      ("#eff6ff", "#1d4ed8", False),
    "plain":    ("#ffffff", GREY, False),
    "agentcore": ("#f5f3ff", "#6d28d9", False),
    "stage":    ("#ffffff", "#6d28d9", False),
    "data":     ("#fafaf9", GREY, False),
    "optional": ("#ffffff", "#a8a29e", True),
    "ops":      ("#ffffff", GREY, True),
}

parts: list[str] = []
problems: list[str] = []

try:
    from PIL import ImageFont
    _fonts = {w: ImageFont.truetype(f"/usr/share/fonts/opentype/inter/Inter-{w}.otf", 100)
              for w in ("Regular", "SemiBold", "Bold")}
except Exception:  # no Pillow or no Inter: skip the fit check
    _fonts = {}


def text_width(text: str, size: float, weight: str = "Regular") -> float:
    if not _fonts:
        return 0
    return _fonts[weight].getlength(text) * size / 100


def text(x, y, s, size=13, weight="Regular", fill=MUTED, anchor="start", spacing=None):
    w = {"Regular": 400, "SemiBold": 600, "Bold": 700}[weight]
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{w}" fill="{fill}" '
                 f'text-anchor="{anchor}"{extra}>{escape(s)}</text>')


def box(x, y, w, h, title, lines=(), style="plain", title2=None, size=12.5, badge=None):
    fill, stroke, dashed = STYLES[style]
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    sw = 2 if style in ("amma", "whatsapp", "ses", "agentcore", "business") else 1.5
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="{sw}"{dash}/>')
    tx = x + 14 + (26 if badge else 0)
    if badge:
        parts.append(f'<circle cx="{x + 25}" cy="{y + 22}" r="11" fill="#6d28d9"/>')
        text(x + 25, y + 26.5, str(badge), size=12.5, weight="Bold", fill="#ffffff", anchor="middle")
    cy = y + 27
    for t in [title] + ([title2] if title2 else []):
        text(tx, cy, t, size=15, weight="SemiBold", fill=INK)
        _fit(t, 15, "SemiBold", x + w - tx - 10)
        cy += 20
    cy += 4
    for line in lines:
        text(x + 14, cy, line, size=size)
        _fit(line, size, "Regular", w - 24)
        cy += size + 5.5
    if cy - size > y + h:
        problems.append(f"'{title}': text runs below the box ({cy - size:.0f} > {y + h})")


def _fit(s, size, weight, room):
    used = text_width(s, size, weight)
    if used > room:
        problems.append(f"'{s}' is {used:.0f}px wide, room {room:.0f}px")


def arrow(points, color=GREY, label=None, label_at=None, dashed=False, both=False):
    d = "M" + " L".join(f"{x} {y}" for x, y in points)
    marker = "arrow-out" if color == AMBER else "arrow"
    start = f' marker-start="url(#{marker})"' if both else ""
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{dash}{start} '
                 f'marker-end="url(#{marker})"/>')
    if label:
        lx, ly = label_at
        text(lx, ly, label, size=11.5, weight="SemiBold", fill=color, anchor="middle")


# ----------------------------------------------------------------------------- layout

PX, PW = 30, 220      # people
CX, CW = 290, 250     # CDS channels
IX, IW = 580, 230     # ingest
AX, AW = 850, 620     # AgentCore
DX, DW = 1500, 230    # data
TOP = 132

parts.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
text(30, 46, "Kavach: WhatsApp scam shield for Indian families, on AWS", size=25, weight="Bold", fill=INK)
text(30, 74, "Region ap-south-1 (Mumbai) · optional email checking in ap-southeast-1 (Singapore) · "
             "grey arrows = coming in, amber = going out to people, dashed = optional or owner-only", size=14.5)
for x, label in ((PX, "PEOPLE AND BUSINESSES"), (CX, "AWS CDS CHANNELS"), (IX, "INGEST"),
                 (AX, "AGENT"), (DX, "DATA AND CONTROL")):
    text(x, 100, label, size=12.5, weight="Bold", fill=SOFT, spacing=1)

# people
box(PX, TOP, PW, 96, "Amma (protected)", ["Forwards texts, links,", "screenshots, PDFs and", "Telugu voice notes"], "amma")
box(PX, 248, PW, 96, "Ravi and family", ["Alerts with \"I'm calling\"", "buttons, emails,", "Sunday digest"], "person")
box(PX, 364, PW, 132, "Member businesses", ["Bank, insurer, pharmacy,", "clinic, home services:",
                                            "channels, rules, masked", "records; get scam reports",
                                            "and appointments"], "business")
box(PX, 516, PW, 100, "Owner (ops mode)", ["\"aws ...\" from WhatsApp:", "health, spend, start or", "stop EC2 after a Yes tap"], "ops")
box(PX, 652, PW, 80, "Email forwarder", ["Forwards a suspicious", "email (optional)"], "optional")

# channels
box(CX, TOP, CW, 200, "AWS End User Messaging", ["Messages, media, voice notes", "Reply buttons: business",
                                                 "actions, family \"I'm calling\",", "ops Yes / Cancel",
                                                 "Templates: family alert,", "district scam warning"],
    "whatsapp", title2="Social (WhatsApp)")
box(CX, 364, CW, 196, "Amazon SES", ["Family alert emails", "Golden-hour report to the", "bank's fraud desk",
                                     "Impersonation reports and", "call-backs to businesses", "Sunday family digest"], "ses")
box(CX, 652, CW, 80, "SES email receiving", ["Singapore · receipt rule", "to S3 and Lambda"], "optional")

# ingest
box(IX, TOP, IW, 64, "Amazon SNS", ["kavach-whatsapp-inbound"])
box(IX, 216, IW, 214, "Inbound Lambda", ["De-duplicate, consent,", "language", "Media to S3, voice to text",
                                         "Business button taps run", "here (no model)", "Ops Yes tap runs the",
                                         "EC2 action", "Sends reply and buttons"])
box(IX, 450, IW, 64, "Amazon Transcribe", ["te-IN · hi-IN · en-IN"])
box(IX, 652, IW, 80, "Email check Lambda", ["Asks the agent, replies", "by email"], "optional")

# AgentCore
parts.append(f'<rect x="{AX}" y="{TOP}" width="{AW}" height="520" rx="12" fill="#f5f3ff" stroke="#6d28d9" stroke-width="2"/>')
text(AX + 16, TOP + 28, "Amazon Bedrock AgentCore Runtime", size=16, weight="Bold", fill=INK)
text(AX + 16, TOP + 49, "Kavach agent (Strands) · Amazon Nova 2 Lite on Amazon Bedrock (global inference profile)", size=12.5)
SY, SW, GAP = TOP + 64, 190, 15
s1, s2, s3 = AX + 10, AX + 10 + SW + GAP, AX + 10 + 2 * (SW + GAP)
box(s1, SY, SW, 196, "Evidence", ["Code, before the model:", "links, numbers, UPI IDs,", "domain age, community",
                                  "reports, India rules", "(TRAI, NPCI, MHA),", "member-business records",
                                  "= verdict floor"], "stage", badge=1)
box(s2, SY, SW, 196, "Agent", ["Nova 2 Lite investigates:", "opens links in AgentCore", "Browser, scam playbooks,",
                               "business records", "Acts: alert family, golden", "hour, business action,",
                               "record verdict"], "stage", badge=2)
box(s3, SY, SW, 196, "Guard", ["Code, after the model:", "never milder than the", "verdict floor; no website",
                               "or number Kavach didn't", "see; one correction, then", "a safe fixed reply"],
    "stage", badge=3)
arrow([(s1 + SW, SY + 98), (s2, SY + 98)])
arrow([(s2 + SW, SY + 98), (s3, SY + 98)])
HW = (AW - 20 - 15) // 2
box(s1, SY + 212, HW, 76, "Everyday helpers", ["Store links from a photo; clinic slots;",
                                               "Swiggy food helper. A tap books or orders"], "stage")
box(s1 + HW + 15, SY + 212, HW, 76, "Ops agent (owner only)", ["View-only AWS tools; start, stop or",
                                                               "reboot only after the owner's Yes"], "ops")
MY = SY + 304
box(s1, MY, SW, 132, "AgentCore Memory", ["Today's conversation;", "long-term facts: bank,", "past scams, family"], "stage")
box(s2, MY, SW, 132, "AgentCore Browser", ["Opens suspicious links", "in an isolated browser;", "never fills forms"], "stage")
box(s3, MY, SW, 132, "Amazon Bedrock", ["Nova 2 Lite reads each", "screenshot and PDF", "\"notice\" once"], "stage")

# data and control
box(DX, TOP, DW, 178, "Amazon DynamoDB", ["users · incidents", "community scam reports", "member-business records",
                                          "clinic bookings", "linked accounts · signals", "pending taps (single use)"], "data")
box(DX, 326, DW, 80, "Amazon S3", ["Media, link screenshots;", "deleted after 7 days"], "data")
box(DX, 422, DW, 64, "SSM Parameter Store", ["/kavach/config"], "data")
box(DX, 502, DW, 80, "Your EC2 instances", ["Started or stopped only", "after the owner's Yes"], "ops")
box(DX, 598, DW, 54, "CloudWatch · Cost Explorer", [], "ops")
box(DX, 668, DW, 80, "Swiggy MCP (official)", ["Food on the person's own", "account; after a tap"], "optional")

# timers and follow-ups
BY = 776
text(1120, BY - 14, "TIMERS AND FOLLOW-UPS", size=12.5, weight="Bold", fill=SOFT, spacing=1)
box(AX, BY, 250, 112, "EventBridge Scheduler", ["5-min family escalation", "15-min golden-hour check-in",
                                                "Sunday 9 AM IST digest"])
box(1120, BY, 190, 112, "escalation", ["Re-alerts family; asks", "\"did you call 1930?\""])
box(1330, BY, 190, 112, "weekly-digest", ["Emails each family", "its week"])
box(1540, BY, 190, 112, "community-alert", ["Warns a district on", "WhatsApp about a", "scam wave"])
arrow([(AX + 250, BY + 56), (1120, BY + 56)])
arrow([(AX + 200, BY + 112), (AX + 200, BY + 128), (1425, BY + 128), (1425, BY + 112)])

# legend
LY = 776
parts.append(f'<rect x="30" y="{LY}" width="780" height="112" rx="10" fill="#fafaf9" stroke="#e7e5e4"/>')
text(46, LY + 26, "How a check flows", size=14, weight="SemiBold", fill=INK)
flow = ["Amma forwards a message on WhatsApp → SNS → Inbound Lambda (voice to text, media to S3)",
        "→ AgentCore: 1 evidence in code, 2 Nova 2 Lite investigates and acts, 3 guard checks the reply",
        "→ reply and business buttons on WhatsApp; family alert template; emails through SES",
        "→ EventBridge timers escalate to family and check that 1930 was called"]
for i, line in enumerate(flow):
    text(46, LY + 50 + i * 18, line, size=12.5)
    _fit(line, 12.5, "Regular", 750)
text(30, 935, "Lambda functions: Python 3.12 on arm64 · shared settings in SSM /kavach/config · media deleted after 7 days · "
              "consent first, STOP turns Kavach off", size=12.5, fill=SOFT)

# ----------------------------------------------------------------------------- arrows between columns

arrow([(PX + PW, 180), (CX, 180)])
arrow([(CX + CW, 164), (IX, 164)])
arrow([(IX + IW / 2, TOP + 64), (IX + IW / 2, 216)])
arrow([(IX + IW / 2, 430), (IX + IW / 2, 450)], both=True)
arrow([(IX + IW, 300), (AX, 300)])
arrow([(IX, 290), (CX + CW, 290)], color=AMBER)
arrow([(AX, 590), (CX + CW, 530)], color=AMBER, label="alerts, reports", label_at=(705, 586))
arrow([(AX + 300, TOP), (AX + 300, 114), (CX + CW / 2 + 60, 114), (CX + CW / 2 + 60, TOP)],
      color=AMBER, label="family alert template", label_at=(705, 127))
arrow([(CX, 300), (PX + PW, 300)], color=AMBER)
arrow([(CX, 400), (PX + PW, 330)], color=AMBER)
arrow([(CX, 450), (PX + PW, 450)], color=AMBER)
arrow([(PX + PW, 692), (CX, 692)], dashed=True)
arrow([(CX + CW, 692), (IX, 692)], dashed=True)
arrow([(IX + IW, 692), (AX + 50, 692), (AX + 50, TOP + 520)], dashed=True)
arrow([(AX + AW, 220), (DX, 220)], both=True)
arrow([(AX + 125, TOP + 520), (AX + 125, BY)], label="timers", label_at=(AX + 160, 700))
arrow([(AX + AW - 60, TOP + 520), (AX + AW - 60, 760), (1635, 760), (1635, BY)], label="scam wave",
      label_at=(AX + AW - 22, 712))

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
       f'font-family="{FONT}">\n<defs>\n'
       f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
       f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{GREY}"/></marker>\n'
       f'<marker id="arrow-out" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
       f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{AMBER}"/></marker>\n</defs>\n'
       + "\n".join(parts) + "\n</svg>\n")

if problems:
    sys.exit("Text does not fit:\n  " + "\n  ".join(problems))
(OUT / "architecture.svg").write_text(svg, encoding="utf-8")
try:
    import cairosvg
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(OUT / "architecture.png"), output_width=W * 2)
    print("Wrote architecture.svg and architecture.png")
except ImportError:
    print("Wrote architecture.svg (install cairosvg for the PNG)")
