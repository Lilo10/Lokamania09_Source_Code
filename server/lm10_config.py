"""Lokamania 10: the fixed choices offered on the application form.

This file is the single place to change categories, spaces, days, statuses
and the application deadline. The public form (index.html) offers the same
keys; the server rejects anything that is not listed here.
"""

from __future__ import annotations

from collections import OrderedDict

EDITION = "Lokamania 10"
REFERENCE_PREFIX = "LM10-"

# Applications close at 11:59 pm Cairo time on 12 November 2026.
# Override with the APPLICATIONS_CLOSE_AT variable (ISO date-time, Cairo time),
# e.g. for testing the "applications closed" page.
DEFAULT_CLOSE_AT = "2026-11-12T23:59:59"

CATEGORIES = OrderedDict([
    ("fashion", "Fashion—Clothing"),
    ("beauty", "Beauty"),
    ("accessories", "Fashion Accessories"),
    ("home", "Home & Lifestyle"),
    ("food", "Food & Beverages"),
    ("art", "Art & Stationery"),
    ("other", "Other"),
])

SUBCATEGORIES = {
    "fashion": ["Women's Wear", "Men's Wear", "Unisex", "Sportswear", "Modest Wear",
                "Streetwear", "Kids' Wear", "Denim", "Basics / Essentials",
                "Swimwear", "Work / Formal"],
    "beauty": ["Makeup", "Skincare", "Haircare", "Perfume", "Body Care", "Beauty Tools"],
    "accessories": ["Jewelry", "Bags", "Shoes", "Sunglasses", "Watches", "Hair Accessories"],
    "home": ["Home Décor", "Candles", "Tableware", "Gifts"],
    "food": ["Desserts", "Snacks", "Beverages", "Packaged Food"],
    "art": ["Art Prints", "Stationery", "Crafts", "Gifts"],
    "other": [],  # "Other" asks the applicant to describe the category instead
}

SPACES = OrderedDict([
    ("kiosk", "The Kiosk (1.5 m × 70 cm)"),
    ("booth", "The Booth (80 cm length × 1.5 m width)"),
    ("cube", "The Mega Cube (4 m width × 3 m length)"),
    ("flagship", "The Flagship (7 m width × 2.5 m length)"),
])

SPACES_BY_CATEGORY = {
    "fashion": ["booth", "cube", "flagship"],
    "beauty": ["kiosk"],
    "accessories": ["kiosk", "booth"],
    "home": ["kiosk", "booth", "cube"],
    "food": ["kiosk"],
    "art": ["kiosk"],
    "other": ["kiosk", "booth", "cube"],
}

DAYS = OrderedDict([
    ("d1", "Day 1 only (Nov 26)"),
    ("d2", "Day 2 only (Nov 27)"),
    ("d3", "Day 3 only (Nov 28)"),
    ("d12", "Days 1 & 2 (Nov 26–27)"),
    ("d23", "Days 2 & 3 (Nov 27–28)"),
    ("all", "All 3 days (Nov 26–28)"),
])

REGISTRATION = ["Yes", "No", "Working on it"]

PRICE_RANGES = ["Under EGP 500", "EGP 500–1,500", "EGP 1,500–3,000", "Above EGP 3,000"]

JOINED = ["No, this is my first time", "1–4 times", "5+ times",
          "I've joined all previous editions"]

STATUSES = ["New", "Under Review", "Contacted", "Accepted", "Waitlisted",
            "Rejected", "Payment Pending", "Confirmed"]
DEFAULT_STATUS = "New"

# Google Sheet columns, in order. The Apps Script writes exactly these headers.
SHEET_COLUMNS = [
    ("reference", "Application Reference"),
    ("submitted_at", "Submitted At (Cairo)"),
    ("brand", "Brand Name"),
    ("launch_year", "Brand Launch Year"),
    ("registration", "Commercial Registration"),
    ("contact", "Contact Person — Full Name"),
    ("phone", "Phone / WhatsApp"),
    ("email", "Email"),
    ("instagram", "Instagram"),
    ("website", "Website"),
    ("about", "About the Brand"),
    ("category", "Main Category"),
    ("subcategory", "Subcategory"),
    ("days", "Participation Days"),
    ("space", "Space"),
    ("products", "Products"),
    ("drop_offer", "Black Friday Drop / Offer"),
    ("price_range", "Typical Price Range"),
    ("joined", "Previous Participation"),
    ("status", "Application Status"),
    ("notes", "Internal Notes"),
    ("last_updated", "Last Updated (Cairo)"),
]
