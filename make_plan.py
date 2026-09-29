#!/usr/bin/env python3
"""Generate a business-friendly deployment plan .docx for Lokamania 09."""
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

GREEN = RGBColor(0x1F, 0x7A, 0x33)
DARK = RGBColor(0x33, 0x33, 0x33)
GRAY = RGBColor(0x66, 0x66, 0x66)

doc = Document()

# Base style
style = doc.styles["Normal"]
style.font.name = "Calibri"
style.font.size = Pt(11)
style.font.color.rgb = DARK

for level, size in (("Heading 1", 16), ("Heading 2", 13)):
    h = doc.styles[level]
    h.font.name = "Calibri"
    h.font.size = Pt(size)
    h.font.color.rgb = GREEN
    h.font.bold = True

def para(text, bold=False, size=11, color=DARK, space_after=6, align=None):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    r.font.color.rgb = color
    p.paragraph_format.space_after = Pt(space_after)
    if align:
        p.alignment = align
    return p

def bullet(text, bold_prefix=None):
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        r = p.add_run(bold_prefix)
        r.bold = True
    p.add_run(text)
    p.paragraph_format.space_after = Pt(4)
    return p

# ---------- Title ----------
para("Lokamania 09 — Website Launch Plan", size=22, bold=True, color=GREEN, align=WD_ALIGN_PARAGRAPH.CENTER)
para("Taking the Lokamania 09 brand website, application form, and admin dashboard live on the internet.", size=12, color=GRAY, align=WD_ALIGN_PARAGRAPH.CENTER)
para("Prepared for: Management   |   Status: For approval", size=10, color=GRAY, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=18)

# ---------- 1. Executive summary ----------
doc.add_heading("1. Executive summary", level=1)
para(
    "The Lokamania 09 website is fully built and working. Visitors can apply through the online "
    "application form, their applications are saved into the master Excel workbook, and the team can "
    "review and update applications through a private admin page. What remains is to put the site on "
    "the internet under a custom web address (domain name) so the public can use it."
)
para(
    "This requires two small purchases: a domain name (around $10–15 per year, renewed annually) and "
    "a web/server plan (around $5–6 per month). Once these are paid for, all the technical setup is "
    "done automatically and takes roughly one hour. Total cost is about $5–6 per month plus $10–15 per "
    "year — very low for a fully functioning brand website with a live application system."
)

# ---------- 2. What is already done ----------
doc.add_heading("2. What is already done (no further cost)", level=1)
bullet("The website is complete and working locally — all pages and the design are final.", bold_prefix="Website: ")
bullet("Applicants can submit applications online, and every submission is saved automatically into the master Excel workbook.", bold_prefix="Application form: ")
bullet("A private admin dashboard lets the team review applications and update their status, payment, and notes without touching Excel.", bold_prefix="Admin dashboard: ")
bullet("The system is protected — the Excel workbook stays the single source of truth, with automatic backups and safety checks to prevent data conflicts.", bold_prefix="Data safety: ")

# ---------- 3. Costs & payment ----------
doc.add_heading("3. What needs to be paid (and to whom)", level=1)
para("The total ongoing cost is approximately $5–6 per month plus $10–15 per year. Full breakdown:")

table = doc.add_table(rows=1, cols=5)
table.style = "Light Grid Accent 1"
table.alignment = WD_TABLE_ALIGNMENT.CENTER
hdr = table.rows[0].cells
for i, t in enumerate(["Item", "Vendor", "Cost (USD)", "When it is paid", "Purpose"]):
    hdr[i].paragraphs[0].add_run(t).bold = True

rows = [
    ("Domain name", "GoDaddy", "$10 – $15", "Once a year (renews annually)", "Your custom web address, e.g. yourbrand.com"),
    ("Website hosting/server", "Hetzner or DigitalOcean", "$5 – $6 per month", "Monthly (can be cancelled anytime)", "Runs the website 24/7 and stores the application data safely"),
    ("Secure connection (HTTPS)", "Included", "$0", "Free, renews automatically", "Padlock icon — keeps customer data secure"),
    ("Daily backups", "Included", "$0", "Free", "Automatic backup of all applications"),
]
for row in rows:
    cells = table.add_row().cells
    for i, val in enumerate(row):
        cells[i].text = val

para("", space_after=2)
para(
    "Note: the amounts above are typical published prices. The final invoice depends on the domain name "
    "chosen (.com, .net, etc.) and the selected hosting plan at the time of purchase.",
    size=10, color=GRAY
)

doc.add_heading("3.1 Recommended payment setup", level=1)
bullet("One payment to GoDaddy for the domain name (paid once per year).", bold_prefix="Domain: ")
bullet("One payment to Hetzner (or DigitalOcean) for hosting, set to renew monthly — can be cancelled at any time with no penalty.", bold_prefix="Hosting: ")
bullet("Both are legitimate, worldwide services that accept standard company/bank cards. No other payments or subscriptions are required.", bold_prefix="Payment method: ")
bullet("The team keeps the account login details in a shared, safe place so only authorised people can renew or cancel.", bold_prefix="Account ownership: ")

# ---------- 4. Deployment steps (reversed: approvals first) ----------
doc.add_heading("4. How we go live — step by step", level=1)
para("The steps are listed in the order they happen, starting with decisions and approvals:")

steps = [
    ("Step 1 — Approve the plan and the budget", "Management confirms the spending above (about $5–6/month + $10–15/year). No money leaves until this is approved."),
    ("Step 2 — Choose the web address", "We agree on the domain name (a short, brandable address such as lokamania.com). Note: this name cannot be changed later, only bought once a year."),
    ("Step 3 — Buy the domain (GoDaddy) and the hosting plan", "The two purchases are made with the company card. This is the only required action."),
    ("Step 4 — Connect the address to the hosting", "A quick click to point the domain name at the new server. This is handled for you."),
    ("Step 5 — Put the website and data on the server", "The completed site and the master Excel workbook are uploaded. Your data keeps its own inbox-like safety backups."),
    ("Step 6 — Final checks and launch", "We test the application form and admin page on the live address, then announce the site."),
]
for title, desc in steps:
    p = doc.add_paragraph()
    r = p.add_run(title)
    r.bold = True
    r.font.color.rgb = GREEN
    p.add_run(" — " + desc)
    p.paragraph_format.space_after = Pt(6)

# ---------- 5. Timeline ----------
doc.add_heading("5. Timeline", level=1)
para("Once payment is approved, the site can be live the same day:")
bullet("Approvals + purchases: same day (about 30 minutes of work).")
bullet("Technical setup (steps 4–6): about 1 hour, done automatically by a setup script.")
bullet("Go-live: the same day as the purchases are confirmed.")

# ---------- 6. After launch ----------
doc.add_heading("6. After launch — how it keeps running", level=1)
bullet("The domain renews once a year (GoDaddy sends a renewal reminder before it expires).", bold_prefix="Domain renewal: ")
bullet("Hosting renews monthly and can be cancelled at any time.", bold_prefix="Hosting: ")
bullet("All applications are backed up automatically every day.", bold_prefix="Backups: ")
bullet("The Excel workbook remains the single source of truth. Everyday updates are made through the admin page; occasional spreadsheet-only edits are done on a backup copy to avoid conflicts.", bold_prefix="Data: ")

# ---------- 7. Risks (plain language) ----------
doc.add_heading("7. Things to be aware of (and how they are handled)", level=1)
bullet("Low and predictable — approximately $5–6/month plus $10–15/year. No hidden or setup fees.", bold_prefix="Cost: ")
bullet("The domain name is the one long-term commitment; it is a standard annual registration that can be moved to any provider at any time.", bold_prefix="Commitment: ")
bullet("The application data can be exported/downloaded at any time as backup files, so the business always owns its data.", bold_prefix="Data ownership: ")

# ---------- 8. Approval ----------
doc.add_heading("8. Approval", level=1)
para("Please confirm the following to proceed:", space_after=8)
approvals = [
    "I approve the total spending of ~$5–6 per month + $10–15 per year for the Lokamania 09 website.",
    "I approve the purchase of a domain name for the website (address to be agreed).",
    "I confirm the payment method (company card or expense) for the two vendors: GoDaddy and Hetzner (or DigitalOcean).",
]
for a in approvals:
    doc.add_paragraph(a)

para("", space_after=4)
para("☐  Approved by: __________________________    Date: ______________", size=11, space_after=10)
para("", space_after=2)
para("Questions? The technical setup is fully automated — nothing else is required beyond the two purchases above.", size=10, color=GRAY)

doc.save("/Users/macbookair/Downloads/Lokamania09_Deployment_Plan.docx")
print("Saved OK")