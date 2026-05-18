"""
Wedding Catering Agent Tools — v2
Reads caterers from caterers.csv (local currency pricing, city-aware).
Replaces the previous hardcoded in-memory database.
"""

import csv
import logging
import asyncio
import os
import smtplib
import ssl
import certifi
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.adk.tools import ToolContext
from solace_agent_mesh.agent.utils.artifact_helpers import (
    save_artifact_with_metadata,
    DEFAULT_SCHEMA_MAX_KEYS,
)
from solace_agent_mesh.agent.utils.context_helpers import get_original_session_id

log = logging.getLogger(__name__)

PLUGIN_NAME = "catering_agent"

# ---------------------------------------------------------------------------
# CSV path — place caterers.csv alongside this file:
#   catering-agent/src/catering_agent/caterers.csv
# ---------------------------------------------------------------------------

_CSV_PATH = Path(__file__).parent / "caterers.csv"

# ---------------------------------------------------------------------------
# Dashboard integration
# ---------------------------------------------------------------------------

WEDDING_DASHBOARD_URL: str = os.environ.get(
    "WEDDING_DASHBOARD_URL",
    "http://localhost:8080/wedding_dashboard.html",
)


def _dashboard_link(extra_msg: str = "") -> str:
    """Return a persistent dashboard link to append to EVERY agent response."""
    return (
        f"\n\n---\n"
        f"📊 **[View Your Wedding Planning Dashboard]({WEDDING_DASHBOARD_URL})** "
        f"— track all vendors in one place.\n"
        + (f"_{extra_msg}_\n" if extra_msg else "")
    )


def _dashboard_update_script(task_id: str, vendor: str, city: str,
                              chosen: bool, emailed: bool, booked: bool) -> str:
    """Return a JS postMessage snippet to auto-update the dashboard."""
    import json
    payload = json.dumps({
        "type": "samUpdateTask",
        "payload": {
            "id":      task_id,
            "vendor":  vendor,
            "city":    city,
            "chosen":  chosen,
            "emailed": emailed,
            "booked":  booked,
        }
    })
    return (
        f"\n\n<script>"
        f"(function(){{try{{window.postMessage({payload},'*');}}"
        f"catch(e){{}}}})();"
        f"</script>"
    )


# ---------------------------------------------------------------------------
# Currency symbol lookup — used for display
# ---------------------------------------------------------------------------

CURRENCY_SYMBOLS: Dict[str, str] = {
    "GBP": "£",
    "JPY": "¥",
    "USD": "$",
    "EUR": "€",
    "INR": "₹",
    "KRW": "₩",
    "SGD": "S$",
    "AUD": "A$",
}

# ---------------------------------------------------------------------------
# Valid option sets
# ---------------------------------------------------------------------------

VALID_CUISINES = {
    "continental", "mediterranean", "indian", "asian_fusion",
    "middle_eastern", "italian", "mexican", "japanese", "thai",
    "american_bbq", "korean", "french", "chinese", "malay",
    "australian", "south_indian",
}

VALID_DIETARY_RESTRICTIONS = {
    "vegetarian", "vegan", "jain", "halal",
    "kosher", "gluten_free", "nut_free", "dairy_free",
}

VALID_DESSERT_OPTIONS = {
    "wedding_cake", "dessert_bar", "sugar_free", "both", "none",
}

# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------

def _load_caterers_from_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Load and parse caterers from caterers.csv into a list of dicts."""
    if not csv_path.exists():
        log.error(f"[{PLUGIN_NAME}] caterers.csv not found at {csv_path}")
        return []

    caterers: List[Dict[str, Any]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                caterer = {
                    "id":   row["caterer_id"].strip(),
                    # CSV uses "caterer_name" column (not "name")
                    "name": row.get("caterer_name", row.get("name", "")).strip(),
                    "city":                    row["city"].strip(),
                    "country":                 row["country"].strip(),
                    "cuisines":                [c.strip() for c in row["cuisines"].split(",")],
                    "min_guests":              int(row["min_guests"]),
                    "max_guests":              int(row["max_guests"]),
                    "base_price_per_head":     float(row["base_price_per_head_local"]),
                    "alcohol_price_per_head":  float(row["alcohol_price_per_head_local"]),
                    "dessert_price_per_head":  float(row["dessert_price_per_head_local"]),
                    "currency":                row["currency"].strip(),
                    "alcohol_service":         row["alcohol_service"].strip().lower() == "true",
                    "dessert_options":         [d.strip() for d in row["dessert_options"].split(",")],
                    "dietary_options":         [d.strip() for d in row["dietary_options"].split(",")],
                    "description":             row["description"].strip(),
                    "contact_email":           row["contact_email"].strip(),
                    "website":                 row["website"].strip(),
                    "packages":                [p.strip() for p in row["packages"].split(",")],
                }
                caterers.append(caterer)
            except (KeyError, ValueError) as exc:
                log.warning(f"[{PLUGIN_NAME}] Skipping malformed CSV row: {exc} — {row}")

    log.info(f"[{PLUGIN_NAME}] Loaded {len(caterers)} caterers from {csv_path}")
    return caterers


# Module-level caterer database (loaded once on import)
_CATERER_DB: List[Dict[str, Any]] = _load_caterers_from_csv(_CSV_PATH)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _currency_symbol(currency: str) -> str:
    """Return the display symbol for a currency code."""
    return CURRENCY_SYMBOLS.get(currency.upper(), currency + " ")


def _fmt_price(amount: float, currency: str) -> str:
    """Format a price with its local currency symbol."""
    sym = _currency_symbol(currency)
    # JPY and KRW are whole-number currencies — no decimal places
    if currency.upper() in ("JPY", "KRW"):
        return f"{sym}{int(amount):,}"
    return f"{sym}{amount:,.2f}"


def _caterer_supports_dietary(caterer: Dict[str, Any], restrictions: List[str]) -> bool:
    """Return True if the caterer supports ALL requested dietary restrictions."""
    supported = set(caterer["dietary_options"])
    return all(r in supported for r in restrictions)


def _calculate_quote(
    caterer: Dict[str, Any],
    guest_count: int,
    include_alcohol: bool,
    dessert_option: str,
) -> Dict[str, float]:
    """Calculate a full pricing breakdown in local currency."""
    food_total    = caterer["base_price_per_head"] * guest_count
    alcohol_total = caterer["alcohol_price_per_head"] * guest_count if include_alcohol else 0.0
    dessert_total = (
        caterer["dessert_price_per_head"] * guest_count
        if dessert_option and dessert_option != "none"
        else 0.0
    )
    grand_total = food_total + alcohol_total + dessert_total
    return {
        "food_total":         round(food_total, 2),
        "alcohol_total":      round(alcohol_total, 2),
        "dessert_total":      round(dessert_total, 2),
        "grand_total":        round(grand_total, 2),
        "price_per_head_total": round(grand_total / guest_count, 2),
    }


def _safe_caterer_summary(caterer: Dict[str, Any]) -> Dict[str, Any]:
    """Return a serialisable summary of a caterer."""
    return {
        "caterer_id":        caterer["id"],
        "name":              caterer["name"],
        "city":              caterer["city"],
        "country":           caterer["country"],
        "cuisines":          caterer["cuisines"],
        "min_guests":        caterer["min_guests"],
        "max_guests":        caterer["max_guests"],
        "base_price_per_head": caterer["base_price_per_head"],
        "currency":          caterer["currency"],
        "alcohol_service":   caterer["alcohol_service"],
        "dessert_options":   caterer["dessert_options"],
        "dietary_options":   caterer["dietary_options"],
        "description":       caterer["description"],
        "contact_email":     caterer["contact_email"],
        "website":           caterer["website"],
        "packages":          caterer["packages"],
        # Formatted price for display
        "base_price_display": _fmt_price(caterer["base_price_per_head"], caterer["currency"]),
    }


# ---------------------------------------------------------------------------
# SMTP helper — sends booking request email to caterer
# ---------------------------------------------------------------------------

def _send_caterer_booking_email(
    caterer: Dict[str, Any],
    quote: Dict[str, Any],
    requester_name: str,
    requester_phone: Optional[str],
) -> Dict[str, Any]:
    """
    Send a booking REQUEST email to the caterer's contact_email from the CSV.
    Uses SMTP with certifi SSL and ASCII password normalisation.
    """
    recipient = caterer["contact_email"]
    cur       = caterer.get("currency", "USD")
    subject   = f"REQUEST TO BOOK — {caterer['name']} — Catering"

    alcohol_str = "Yes" if quote.get("include_alcohol") else "No"
    dessert_str = quote.get("dessert_option", "none").replace("_", " ").title()
    diet_str    = ", ".join(quote.get("dietary_accommodated", [])) or "None specified"

    body = f"""Dear {caterer['name']} Team,

⚠️  THIS IS A REQUEST TO BOOK — NOT A CONFIRMED RESERVATION.

I am writing on behalf of {requester_name} to formally request to book your catering services for an upcoming wedding. No booking is confirmed until you respond and both parties agree in writing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CATERING BOOKING REQUEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Caterer           : {caterer['name']}
  City              : {caterer['city']}, {caterer['country']}
  Guest Count       : {quote.get('guest_count', 'TBD')} guests
  Cuisine(s)        : {', '.join(caterer['cuisines'])}
  Alcohol Service   : {alcohol_str}
  Dessert Option    : {dessert_str}
  Dietary Needs     : {diet_str}
  Grand Total (est) : {quote.get('grand_total_display', 'TBD')} ({cur})

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REQUESTER CONTACT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Name              : {requester_name}
  Phone             : {requester_phone if requester_phone else 'Please reply to this email'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please reply to confirm availability, advise on tasting session scheduling,
and share your contract and deposit requirements.

Kind regards,
Wedding Planning with SAM — Automated Booking System
"""

    log.info(f"[{PLUGIN_NAME}] Sending catering booking request to {recipient} for {caterer['name']}")

    try:
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USERNAME", "samdevuser@gmail.com")
        smtp_pass = os.environ.get("SMTP_PASSWORD", "gxtm bdtg tbyh icvt")
        sender    = os.environ.get("SMTP_FROM_ADDRESS", smtp_user)

        # Strip non-ASCII characters (fixes non-breaking space in copy-pasted App Passwords)
        smtp_pass = "".join(c for c in smtp_pass if ord(c) < 128).strip()

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Wedding Planning with SAM <{sender}>"
        msg["To"]      = recipient
        msg.attach(MIMEText(body, "plain"))

        # certifi CA bundle — fixes macOS SSL certificate verification error
        tls_ctx = ssl.create_default_context(cafile=certifi.where())
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls(context=tls_ctx)
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(sender, [recipient], msg.as_string())

        log.info(f"[{PLUGIN_NAME}] ✅ Catering booking request email sent to {recipient}")
        return {"status": "success", "recipient": recipient, "subject": subject}

    except Exception as exc:
        log.exception(f"[{PLUGIN_NAME}] Failed to send catering booking email: {exc}")
        return {"status": "error", "message": f"Failed to send email: {exc}"}


# ---------------------------------------------------------------------------
# Tool 1 — get_cuisine_options
# ---------------------------------------------------------------------------

async def get_cuisine_options(
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Return the list of available cuisine styles, dietary options, and dessert choices.
    Call this first to present options to the user before searching.
    """
    log_identifier = f"[{PLUGIN_NAME}:get_cuisine_options]"
    log.info(f"{log_identifier} Returning all available cuisine options.")

    cuisine_descriptions = {
        "continental":    "Classic European dishes — roasts, gratins, sauces, and elegant mains.",
        "mediterranean":  "Fresh flavours from Greece, Spain & the Levant — mezze, seafood, olive oil.",
        "indian":         "Rich curries, tandoor specialties, biryanis, and street-food stations.",
        "south_indian":   "Sadya feast, dosas, appam, sambhar, and aromatic rice dishes.",
        "asian_fusion":   "Creative East-meets-West dishes blending Asian ingredients with global techniques.",
        "middle_eastern": "Mezze platters, shawarma, hummus, and aromatic slow-cooked meats.",
        "italian":        "Pasta, risotto, wood-fired pizza, antipasti, and premium wine pairings.",
        "french":         "Classic French gastronomy — butter sauces, charcuterie, and fine patisserie.",
        "mexican":        "Tacos, enchiladas, guacamole stations, and vibrant street-food spreads.",
        "japanese":       "Sushi, sashimi, teppanyaki, ramen bars, and refined kaiseki courses.",
        "korean":         "Hanjeonsik feast, galbi, bibimbap, kimchi stations, and Korean barbecue.",
        "thai":           "Fragrant curries, pad thai, satay skewers, and tropical desserts.",
        "chinese":        "Dim sum, Peking duck, wok stations, and traditional banquet menus.",
        "malay":          "Nasi lemak, rendang, satay, and laksa — vibrant Southeast Asian flavours.",
        "australian":     "Modern Australian cuisine — native ingredients, seafood, and bush tucker.",
        "american_bbq":   "Smoked meats, craft sides, mac & cheese stations, and comfort classics.",
    }

    return {
        "status":  "success",
        "message": "Here are the available cuisine styles. Ask the user to select one or more.",
        "cuisines": [
            {"id": k, "description": v}
            for k, v in cuisine_descriptions.items()
        ],
        "dietary_options": [
            {"id": "vegetarian",  "description": "No meat or seafood; dairy and eggs permitted."},
            {"id": "vegan",       "description": "No animal products whatsoever."},
            {"id": "jain",        "description": "No meat, eggs, root vegetables (onion, garlic, potato, etc.)."},
            {"id": "halal",       "description": "Meat slaughtered and prepared per Islamic law."},
            {"id": "kosher",      "description": "Prepared and served in accordance with Jewish dietary law."},
            {"id": "gluten_free", "description": "No wheat, barley, rye or gluten-containing ingredients."},
            {"id": "nut_free",    "description": "No tree nuts or peanuts in any dish."},
            {"id": "dairy_free",  "description": "No milk, cheese, butter or dairy derivatives."},
        ],
        "dessert_options": [
            {"id": "wedding_cake", "description": "Traditional tiered wedding cake only."},
            {"id": "dessert_bar",  "description": "Full dessert station with variety of sweets."},
            {"id": "sugar_free",   "description": "Sugar-free / diabetic-friendly dessert alternatives."},
            {"id": "both",         "description": "Wedding cake PLUS a dessert bar."},
            {"id": "none",         "description": "No dessert service required."},
        ],
        "beverage_note": (
            "Please also confirm: (1) Is alcohol service required? "
            "(2) Any specific beverage preferences (open bar, wine & beer only, mocktails only)?"
        ),
        "note": (
            f"All prices are shown in the local currency of the venue city. "
            f"Currencies used: GBP (London), JPY (Tokyo), USD (New York City), "
            f"EUR (Paris), INR (Mumbai), KRW (Seoul), SGD (Singapore), AUD (Sydney)."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 2 — search_caterers
# ---------------------------------------------------------------------------

async def search_caterers(
    guest_count: int,
    cuisines: str,
    city: Optional[str] = None,
    dietary_restrictions: Optional[str] = None,
    include_alcohol: Optional[bool] = None,
    dessert_option: Optional[str] = None,
    budget_per_head: Optional[float] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Search for available caterers from the CSV database matching the requirements.

    Args:
        guest_count:          Required. Number of guests.
        cuisines:             Required. Comma-separated cuisine types.
        city:                 Optional. Filter by city (e.g. 'London', 'Tokyo', 'Mumbai').
                              If not provided, searches all cities.
        dietary_restrictions: Optional. Comma-separated dietary restrictions.
        include_alcohol:      Optional. True if alcohol service is required.
        dessert_option:       Optional. One of: wedding_cake, dessert_bar, sugar_free, both, none.
        budget_per_head:      Optional. Maximum budget per guest in local currency.
        tool_context:         Injected by the Solace Agent Mesh runtime.
        tool_config:          Optional runtime configuration dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:search_caterers]"
    log.info(
        f"{log_identifier} guest_count={guest_count} cuisines={cuisines!r} "
        f"city={city!r} dietary={dietary_restrictions!r} alcohol={include_alcohol} "
        f"dessert={dessert_option!r} budget_per_head={budget_per_head}"
    )

    # ── Validation ──────────────────────────────────────────────────────────
    if not isinstance(guest_count, int) or guest_count <= 0:
        return {
            "status":  "error",
            "message": f"guest_count must be a positive integer, got {guest_count!r}.",
        }

    requested_cuisines = [c.strip().lower() for c in cuisines.split(",") if c.strip()]
    if not requested_cuisines:
        return {"status": "error", "message": "At least one cuisine must be specified."}

    requested_dietary: List[str] = []
    if dietary_restrictions:
        requested_dietary = [
            d.strip().lower() for d in dietary_restrictions.split(",") if d.strip()
        ]
        invalid_diet = [d for d in requested_dietary if d not in VALID_DIETARY_RESTRICTIONS]
        if invalid_diet:
            return {
                "status":  "error",
                "message": (
                    f"Invalid dietary restriction(s): {invalid_diet}. "
                    f"Valid options: {sorted(VALID_DIETARY_RESTRICTIONS)}"
                ),
            }

    if dessert_option and dessert_option not in VALID_DESSERT_OPTIONS:
        return {
            "status":  "error",
            "message": (
                f"Invalid dessert_option '{dessert_option}'. "
                f"Valid options: {sorted(VALID_DESSERT_OPTIONS)}"
            ),
        }

    # ── Filter ───────────────────────────────────────────────────────────────
    results: List[Dict[str, Any]] = []

    for caterer in _CATERER_DB:

        # City filter (case-insensitive, optional)
        if city and city.strip().lower() not in caterer["city"].lower():
            continue

        # Cuisine match — caterer must support at least one requested cuisine
        caterer_cuisines = set(caterer["cuisines"])
        if not any(c in caterer_cuisines for c in requested_cuisines):
            continue

        # Guest capacity check
        if not (caterer["min_guests"] <= guest_count <= caterer["max_guests"]):
            continue

        # Alcohol check
        if include_alcohol is True and not caterer["alcohol_service"]:
            continue

        # Dessert check
        if dessert_option and dessert_option != "none":
            if dessert_option not in caterer["dessert_options"]:
                continue

        # Dietary restrictions check
        if requested_dietary and not _caterer_supports_dietary(caterer, requested_dietary):
            continue

        # Budget check (total per head in local currency)
        if budget_per_head is not None:
            quote = _calculate_quote(
                caterer,
                guest_count,
                include_alcohol or False,
                dessert_option or "none",
            )
            if quote["price_per_head_total"] > budget_per_head:
                continue

        results.append(_safe_caterer_summary(caterer))

    # Sort by base_price_per_head ascending
    results.sort(key=lambda c: c["base_price_per_head"])

    # Determine currency for display note
    sample_currency = results[0]["currency"] if results else "local currency"

    log.info(f"{log_identifier} Found {len(results)} matching caterer(s).")
    return {
        "status":        "success",
        "message":       f"Found {len(results)} caterer(s) matching your requirements.",
        "total_results": len(results),
        "caterers":      results,
        "currency_note": f"All prices shown in {sample_currency}.",
        "search_criteria": {
            "guest_count":        guest_count,
            "city":               city,
            "cuisines":           requested_cuisines,
            "dietary_restrictions": requested_dietary or None,
            "include_alcohol":    include_alcohol,
            "dessert_option":     dessert_option,
            "budget_per_head":    budget_per_head,
        },
    }


# ---------------------------------------------------------------------------
# Tool 3 — get_caterer_details
# ---------------------------------------------------------------------------

async def get_caterer_details(
    caterer_id: str,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Retrieve full details for a single caterer by its ID (e.g. 'C001').

    Args:
        caterer_id:   Required. The caterer identifier.
        tool_context: Injected by the Solace Agent Mesh runtime.
        tool_config:  Optional runtime configuration dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:get_caterer_details]"
    log.info(f"{log_identifier} caterer_id={caterer_id!r}")

    if not caterer_id or not caterer_id.strip():
        return {"status": "error", "message": "caterer_id must not be empty."}

    caterer_id = caterer_id.strip().upper()

    for caterer in _CATERER_DB:
        if caterer["id"] == caterer_id:
            log.info(f"{log_identifier} Found: {caterer['name']}")
            return {
                "status":  "success",
                "message": f"Caterer '{caterer['name']}' retrieved successfully.",
                "caterer": _safe_caterer_summary(caterer),
            }

    log.warning(f"{log_identifier} Caterer not found: {caterer_id!r}")
    return {
        "status":  "error",
        "message": (
            f"No caterer found with ID '{caterer_id}'. "
            f"Valid IDs: {[c['id'] for c in _CATERER_DB]}"
        ),
    }


# ---------------------------------------------------------------------------
# Tool 4 — get_catering_quote
# ---------------------------------------------------------------------------

async def get_catering_quote(
    caterer_id: str,
    guest_count: int,
    include_alcohol: bool,
    dessert_option: str,
    dietary_restrictions: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate a detailed catering quote for a specific caterer.
    All prices are returned in the caterer's local currency.

    Args:
        caterer_id:           Required. The caterer identifier (e.g. 'C002').
        guest_count:          Required. Number of guests.
        include_alcohol:      Required. True if alcohol service is required.
        dessert_option:       Required. One of: wedding_cake, dessert_bar, sugar_free, both, none.
        dietary_restrictions: Optional. Comma-separated dietary restrictions.
        tool_context:         Injected by the Solace Agent Mesh runtime.
        tool_config:          Optional runtime configuration dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:get_catering_quote]"
    log.info(
        f"{log_identifier} caterer_id={caterer_id!r} guest_count={guest_count} "
        f"alcohol={include_alcohol} dessert={dessert_option!r} "
        f"dietary={dietary_restrictions!r}"
    )

    if not caterer_id or not caterer_id.strip():
        return {"status": "error", "message": "caterer_id must not be empty."}

    if not isinstance(guest_count, int) or guest_count <= 0:
        return {
            "status":  "error",
            "message": f"guest_count must be a positive integer, got {guest_count!r}.",
        }

    if dessert_option not in VALID_DESSERT_OPTIONS:
        return {
            "status":  "error",
            "message": (
                f"Invalid dessert_option '{dessert_option}'. "
                f"Valid options: {sorted(VALID_DESSERT_OPTIONS)}"
            ),
        }

    caterer_id = caterer_id.strip().upper()

    for caterer in _CATERER_DB:
        if caterer["id"] != caterer_id:
            continue

        cur = caterer["currency"]

        # Capacity check
        if not (caterer["min_guests"] <= guest_count <= caterer["max_guests"]):
            return {
                "status":  "error",
                "message": (
                    f"Guest count {guest_count} is outside '{caterer['name']}' "
                    f"capacity range ({caterer['min_guests']}–{caterer['max_guests']})."
                ),
            }

        # Alcohol check
        if include_alcohol and not caterer["alcohol_service"]:
            return {
                "status":  "error",
                "message": (
                    f"'{caterer['name']}' does not offer alcohol service. "
                    "Please choose a different caterer or opt out of alcohol."
                ),
            }

        # Dessert check
        if dessert_option != "none" and dessert_option not in caterer["dessert_options"]:
            return {
                "status":  "error",
                "message": (
                    f"'{caterer['name']}' does not offer the '{dessert_option}' dessert option. "
                    f"Available options: {caterer['dessert_options']}"
                ),
            }

        # Dietary check
        requested_dietary: List[str] = []
        if dietary_restrictions:
            requested_dietary = [
                d.strip().lower()
                for d in dietary_restrictions.split(",")
                if d.strip()
            ]
            if not _caterer_supports_dietary(caterer, requested_dietary):
                unsupported = [
                    d for d in requested_dietary if d not in caterer["dietary_options"]
                ]
                return {
                    "status":  "error",
                    "message": (
                        f"'{caterer['name']}' does not support: {unsupported}. "
                        f"Supported: {caterer['dietary_options']}"
                    ),
                }

        # ── Calculate quote ──────────────────────────────────────────────────
        pricing = _calculate_quote(caterer, guest_count, include_alcohol, dessert_option)

        log.info(
            f"{log_identifier} Quote: {caterer['name']} = "
            f"{_fmt_price(pricing['grand_total'], cur)} for {guest_count} guests"
        )

        return {
            "status":  "success",
            "message": (
                f"Quote generated for '{caterer['name']}' — "
                f"estimated total {_fmt_price(pricing['grand_total'], cur)} "
                f"for {guest_count} guests."
            ),
            "quote": {
                "caterer_id":             caterer["id"],
                "caterer_name":           caterer["caterer_name"],
                "city":                   caterer["city"],
                "country":                caterer["country"],
                "cuisines":               caterer["cuisines"],
                "currency":               cur,
                "guest_count":            guest_count,
                "include_alcohol":        include_alcohol,
                "dessert_option":         dessert_option,
                "dietary_accommodated":   requested_dietary or [],
                "base_price_per_head":    caterer["base_price_per_head"],
                "base_price_display":     _fmt_price(caterer["base_price_per_head"], cur),
                "alcohol_price_per_head": caterer["alcohol_price_per_head"] if include_alcohol else 0.0,
                "alcohol_price_display":  _fmt_price(caterer["alcohol_price_per_head"] if include_alcohol else 0.0, cur),
                "dessert_price_per_head": caterer["dessert_price_per_head"] if dessert_option != "none" else 0.0,
                "dessert_price_display":  _fmt_price(caterer["dessert_price_per_head"] if dessert_option != "none" else 0.0, cur),
                "price_per_head_total":   pricing["price_per_head_total"],
                "price_per_head_display": _fmt_price(pricing["price_per_head_total"], cur),
                "food_subtotal":          pricing["food_total"],
                "food_subtotal_display":  _fmt_price(pricing["food_total"], cur),
                "alcohol_subtotal":       pricing["alcohol_total"],
                "alcohol_subtotal_display": _fmt_price(pricing["alcohol_total"], cur),
                "dessert_subtotal":       pricing["dessert_total"],
                "dessert_subtotal_display": _fmt_price(pricing["dessert_total"], cur),
                "grand_total":            pricing["grand_total"],
                "grand_total_display":    _fmt_price(pricing["grand_total"], cur),
                "packages_available":     caterer["packages"],
                "contact_email":          caterer["contact_email"],
                "website":                caterer["website"],
                "next_steps": (
                    "Contact the caterer to arrange a tasting session, "
                    "confirm the menu, and sign the catering agreement."
                ),
            },
        }

    log.warning(f"{log_identifier} Caterer not found: {caterer_id!r}")
    return {
        "status":  "error",
        "message": f"No caterer found with ID '{caterer_id}'.",
    }


# ---------------------------------------------------------------------------
# Tool 5 — save_catering_quote_report
# ---------------------------------------------------------------------------

async def save_catering_quote_report(
    filename: str,
    caterer_id: str,
    guest_count: int,
    include_alcohol: bool,
    dessert_option: str,
    dietary_restrictions: Optional[str] = None,
    requester_name: str = "Wedding Planning Guest",
    requester_phone: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate a catering quote and save it as a text report artifact.
    This triggers a booking REQUEST email — not a confirmed reservation.

    Args:
        filename:             Required. Desired output filename (e.g. 'catering_quote').
        caterer_id:           Required. The caterer identifier (e.g. 'C002').
        guest_count:          Required. Number of guests.
        include_alcohol:      Required. True if alcohol service is required.
        dessert_option:       Required. One of: wedding_cake, dessert_bar, sugar_free, both, none.
        dietary_restrictions: Optional. Comma-separated dietary restriction strings.
        requester_name:       Required. Full name of the person making the request.
                              Must be collected from the user before calling this tool.
        requester_phone:      Required. Phone number of the requester.
                              Must be collected from the user before calling this tool.
        tool_context:         Injected by the Solace Agent Mesh runtime.
        tool_config:          Optional runtime configuration dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:save_catering_quote_report]"
    log.info(f"{log_identifier} Saving catering report to '{filename}'")

    if not tool_context or not tool_context._invocation_context:
        return {
            "status":  "error",
            "message": "ToolContext or InvocationContext is missing. Cannot save artifact.",
        }

    inv_context      = tool_context._invocation_context
    app_name         = getattr(inv_context, "app_name", None)
    user_id          = getattr(inv_context, "user_id", None)
    session_id       = get_original_session_id(inv_context)
    artifact_service = getattr(inv_context, "artifact_service", None)

    if not all([app_name, user_id, session_id, artifact_service]):
        missing = [
            label for label, val in [
                ("app_name",         app_name),
                ("user_id",          user_id),
                ("session_id",       session_id),
                ("artifact_service", artifact_service),
            ] if not val
        ]
        return {
            "status":  "error",
            "message": f"Missing required context parts: {', '.join(missing)}",
        }

    # ── Generate the quote ──────────────────────────────────────────────────
    quote_result = await get_catering_quote(
        caterer_id=caterer_id,
        guest_count=guest_count,
        include_alcohol=include_alcohol,
        dessert_option=dessert_option,
        dietary_restrictions=dietary_restrictions,
        tool_context=tool_context,
        tool_config=tool_config,
    )

    if quote_result.get("status") == "error":
        return quote_result

    q         = quote_result["quote"]
    cur       = q["currency"]
    timestamp = datetime.now(timezone.utc)

    # ── Build report text ───────────────────────────────────────────────────
    lines = [
        "=" * 70,
        "WEDDING CATERING QUOTE REPORT",
        f"Generated : {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 70,
        "",
        "CATERER DETAILS",
        "-" * 40,
        f"  Caterer          : {q['caterer_name']} ({q['caterer_id']})",
        f"  City             : {q['city']}, {q['country']}",
        f"  Cuisines         : {', '.join(q['cuisines'])}",
        f"  Contact Email    : {q['contact_email']}",
        f"  Website          : {q['website']}",
        "",
        "EVENT REQUIREMENTS",
        "-" * 40,
        f"  Guest Count      : {q['guest_count']}",
        f"  Alcohol Service  : {'Yes' if q['include_alcohol'] else 'No'}",
        f"  Dessert Option   : {q['dessert_option'].replace('_', ' ').title()}",
        f"  Dietary Needs    : {', '.join(q['dietary_accommodated']) if q['dietary_accommodated'] else 'None specified'}",
        "",
        f"PRICING BREAKDOWN  (all prices in {cur})",
        "-" * 40,
        f"  Food (per head)       : {q['base_price_display']}",
        f"  Alcohol (per head)    : {q['alcohol_price_display']}",
        f"  Dessert (per head)    : {q['dessert_price_display']}",
        f"  Total (per head)      : {q['price_per_head_display']}",
        "",
        f"  Food Subtotal         : {q['food_subtotal_display']}",
        f"  Alcohol Subtotal      : {q['alcohol_subtotal_display']}",
        f"  Dessert Subtotal      : {q['dessert_subtotal_display']}",
        "",
        f"  GRAND TOTAL           : {q['grand_total_display']}",
        "",
        "AVAILABLE PACKAGES",
        "-" * 40,
        f"  {', '.join(p.title() for p in q['packages_available'])}",
        "",
        "NEXT STEPS",
        "-" * 40,
        f"  {q['next_steps']}",
        "",
        "=" * 70,
        "END OF REPORT",
        "=" * 70,
    ]

    report_text = "\n".join(lines)
    output_filename = filename.strip()
    if not output_filename.lower().endswith(".txt"):
        output_filename += ".txt"

    content_bytes = report_text.encode("utf-8")
    metadata_dict = {
        "description":            f"Catering quote report generated by {PLUGIN_NAME}.",
        "source_tool":            "save_catering_quote_report",
        "caterer_id":             caterer_id,
        "guest_count":            guest_count,
        "grand_total":            q["grand_total"],
        "currency":               cur,
        "creation_timestamp_iso": timestamp.isoformat(),
    }

    try:
        save_result = await save_artifact_with_metadata(
            artifact_service=artifact_service,
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            filename=output_filename,
            content_bytes=content_bytes,
            mime_type="text/plain",
            metadata_dict=metadata_dict,
            timestamp=timestamp,
            schema_max_keys=DEFAULT_SCHEMA_MAX_KEYS,
            tool_context=tool_context,
        )

        if save_result.get("status") == "error":
            return {
                "status":  "error",
                "message": f"Failed to save artifact: {save_result.get('message')}",
            }

        log.info(
            f"{log_identifier} Artifact '{output_filename}' "
            f"v{save_result['data_version']} saved successfully."
        )
        return {
            "status":          "success",
            "message": (
                f"Catering quote report '{output_filename}' saved as artifact "
                f"v{save_result['data_version']}. "
                f"Grand total: {q['grand_total_display']}."
            ),
            "output_filename": output_filename,
            "output_version":  save_result["data_version"],
            "grand_total":     q["grand_total"],
            "currency":        cur,
            "requester_name":  requester_name,
            "requester_phone": requester_phone,
        }

        # After saving the artifact, send SMTP booking request email
        # to the caterer's actual contact_email from the CSV
        caterer_obj = next((c for c in _CATERER_DB if c["id"] == caterer_id.strip().upper()), None)
        email_sent_to = "unknown"
        email_note    = "Email could not be sent — caterer not found in database."
        if caterer_obj:
            email_result = _send_caterer_booking_email(
                caterer=caterer_obj,
                quote=q,
                requester_name=requester_name,
                requester_phone=requester_phone,
            )
            email_sent_to = email_result.get("recipient", caterer_obj["contact_email"])
            email_note = (
                f"Booking request email sent to {email_sent_to}."
                if email_result.get("status") == "success"
                else f"⚠️ Email error: {email_result.get('message', 'unknown')}"
            )

        return {
            "status":         "success",
            "message":        f"Catering quote saved. Grand total: {q['grand_total_display']}. {email_note}",
            "output_filename": output_filename,
            "output_version": save_result["data_version"],
            "grand_total":    q["grand_total"],
            "currency":       cur,
            "email_sent_to":  email_sent_to,
            "requester_name": requester_name,
            "requester_phone": requester_phone,
            "agent_response": (
                f"✅ A **booking request** for {q['caterer_name']} has been sent to "
                f"{email_sent_to} on your behalf.\n\n"
                f"⚠️ This is a **request only** — NOT confirmed until the caterer replies "
                f"and both parties agree in writing.\n\n"
                f"Let's now choose your decorator!"
                + _dashboard_link("Catering booking request sent — dashboard updated!")
            ),
            "dashboard_update": _dashboard_update_script(
                task_id="catering",
                vendor=q["caterer_name"],
                city=q["city"],
                chosen=True,
                emailed=True,
                booked=False,
            ),
        }

    except Exception as exc:
        log.exception(f"{log_identifier} Unexpected error during artifact saving: {exc}")
        return {
            "status":  "error",
            "message": f"An unexpected error occurred during artifact saving: {exc}",
        }


# ---------------------------------------------------------------------------
# Standalone test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def run_tests():
        print("=" * 70)
        print("CATERING AGENT v2 — CSV-BACKED STANDALONE TESTS")
        print("=" * 70)
        print(f"\nCSV path : {_CSV_PATH}")
        print(f"Loaded   : {len(_CATERER_DB)} caterers")

        class MockArtifactService:
            async def save_artifact(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}", "version": 1}
            async def save_artifact_metadata(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}.meta", "version": 1}

        class MockInvocationContext:
            def __init__(self):
                self.app_name         = "test_catering_app"
                self.user_id          = "test_user"
                self.session_id       = "test_session_001"
                self.artifact_service = MockArtifactService()

        class MockToolContext:
            def __init__(self):
                self._invocation_context = MockInvocationContext()

        mock_ctx = MockToolContext()

        # Test 1: get_cuisine_options
        print("\n--- Test 1: get_cuisine_options ---")
        r1 = await get_cuisine_options(tool_context=mock_ctx)
        print(f"Status  : {r1['status']}")
        print(f"Cuisines: {[c['id'] for c in r1['cuisines']]}")

        # Test 2: search London Indian + Jain
        print("\n--- Test 2: search London indian/jain (200 guests, no alcohol) ---")
        r2 = await search_caterers(
            guest_count=200, cuisines="indian",
            city="London",
            dietary_restrictions="jain,vegetarian",
            include_alcohol=False, dessert_option="dessert_bar",
            tool_context=mock_ctx,
        )
        print(f"Status : {r2['status']} | Found: {r2.get('total_results', 0)}")
        for c in r2.get("caterers", []):
            print(f"  • {c['name']} ({c['city']}) — {c['base_price_display']}/head [{c['currency']}]")

        # Test 3: search Mumbai
        print("\n--- Test 3: search Mumbai indian (300 guests) ---")
        r3 = await search_caterers(
            guest_count=300, cuisines="indian,south_indian",
            city="Mumbai", tool_context=mock_ctx,
        )
        print(f"Status : {r3['status']} | Found: {r3.get('total_results', 0)}")
        for c in r3.get("caterers", []):
            print(f"  • {c['name']} — {c['base_price_display']}/head [{c['currency']}]")

        # Test 4: get_catering_quote
        print("\n--- Test 4: get_catering_quote (C001, 200 guests, London) ---")
        r4 = await get_catering_quote(
            caterer_id="C001", guest_count=200,
            include_alcohol=True, dessert_option="dessert_bar",
            dietary_restrictions="vegetarian",
            tool_context=mock_ctx,
        )
        print(f"Status : {r4['status']}")
        if r4["status"] == "success":
            q = r4["quote"]
            print(f"Caterer     : {q['caterer_name']}")
            print(f"Currency    : {q['currency']}")
            print(f"Grand Total : {q['grand_total_display']}")
            print(f"Per Head    : {q['price_per_head_display']}")

        # Test 5: save report
        print("\n--- Test 5: save_catering_quote_report ---")
        r5 = await save_catering_quote_report(
            filename="london_catering_quote",
            caterer_id="C001", guest_count=200,
            include_alcohol=True, dessert_option="dessert_bar",
            dietary_restrictions="vegetarian",
            tool_context=mock_ctx,
        )
        print(f"Status  : {r5['status']}")
        print(f"Message : {r5['message']}")

        print("\n" + "=" * 70)
        print("All tests complete.")
        print("=" * 70)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    asyncio.run(run_tests())