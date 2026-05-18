"""
Wedding Photo Agent Tools
A specialized agent for finding wedding photographers and videographers
based on city, style, and package preferences.
Triggered automatically after the Decorator Agent confirms a booking.
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

PLUGIN_NAME = "photo_agent"

# ---------------------------------------------------------------------------
# CSV path — place photographers.csv alongside this file:
#   photo-agent/src/photo_agent/photographers.csv
# ---------------------------------------------------------------------------

_CSV_PATH = Path(__file__).parent / "photographers.csv"

# ---------------------------------------------------------------------------
# Package definitions — single source of truth
# ---------------------------------------------------------------------------

PACKAGES = {
    "photos_only_300": {
        "id":          "photos_only_300",
        "name":        "Essential Photos — 300 Edited Images",
        "includes":    [
            "Up to 8 hours of photography coverage",
            "300 professionally edited high-resolution images",
            "Online gallery with download link (delivered in 4–6 weeks)",
            "Print release included",
        ],
        "video":       False,
        "photo_count": 300,
        "price_note":  "Base package — ideal for intimate weddings",
    },
    "photos_only_500": {
        "id":          "photos_only_500",
        "name":        "Signature Photos — 500 Edited Images",
        "includes":    [
            "Up to 10 hours of photography coverage",
            "500 professionally edited high-resolution images",
            "Online gallery with download link (delivered in 4–6 weeks)",
            "Engagement / pre-shoot session (1 hour)",
            "Print release included",
            "USB with all images",
        ],
        "video":       False,
        "photo_count": 500,
        "price_note":  "Most popular photos-only package",
    },
    "photos_and_video": {
        "id":          "photos_and_video",
        "name":        "Photos + Wedding Film",
        "includes":    [
            "Up to 10 hours of photography coverage",
            "400 professionally edited high-resolution images",
            "Online gallery with download link",
            "Full wedding film (20–30 min cinematic edit, delivered in 8–10 weeks)",
            "3–5 minute wedding highlight trailer (social media ready)",
            "Engagement / pre-shoot session (1 hour)",
            "Print release and USB included",
        ],
        "video":       True,
        "photo_count": 400,
        "price_note":  "Best value — photos and full cinematic film",
    },
    "full_cinematic": {
        "id":          "full_cinematic",
        "name":        "Full Cinematic Experience",
        "includes":    [
            "Full day photography coverage (up to 12 hours, 2 photographers)",
            "600+ professionally edited high-resolution images",
            "Online gallery with download link",
            "Full cinematic wedding film (30–45 min edit, delivered in 10–12 weeks)",
            "5–7 minute highlight trailer with music sync",
            "Same-day edit teaser (played at reception)",
            "Drone aerial footage (subject to location permissions)",
            "Engagement / pre-shoot session (2 hours)",
            "Luxury print album (30 pages)",
            "USB with all content",
        ],
        "video":       True,
        "photo_count": 600,
        "price_note":  "The ultimate wedding memory package — nothing missed",
    },
}

VALID_CITIES = {
    "london", "tokyo", "new york city", "paris",
    "mumbai", "seoul", "singapore", "sydney",
}

VALID_STYLES = {
    "romantic", "documentary", "candid", "fine_art", "editorial",
    "cinematic", "natural", "traditional", "luxury", "rustic",
    "minimalist", "bollywood", "multicultural", "coastal",
}


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------

def _load_photographers_from_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Load and parse photographers from CSV into a list of dicts."""
    if not csv_path.exists():
        log.error(f"[{PLUGIN_NAME}] photographers.csv not found at {csv_path}")
        return []

    photographers: List[Dict[str, Any]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                p = {
                    "id":              row["photographer_id"].strip(),
                    "name":            row["name"].strip(),
                    "city":            row["city"].strip(),
                    "country":         row["country"].strip(),
                    "specializes_in":  [s.strip() for s in row["specializes_in"].split(",")],
                    "style":           [s.strip() for s in row["style"].split(",")],
                    "packages":        [p.strip() for p in row["packages"].split("|")],
                    "min_budget_local":  float(row["min_budget_local"]),
                    "max_budget_local":  float(row["max_budget_local"]),
                    "contact_email":   row["contact_email"].strip(),
                    "website":         row["website"].strip(),
                    "instagram":       row["instagram"].strip(),
                    "description":     row["description"].strip(),
                    "currency":         row["currency"].strip(),
                }
                photographers.append(p)
            except (KeyError, ValueError) as exc:
                log.warning(f"[{PLUGIN_NAME}] Skipping malformed CSV row: {exc} — {row}")

    log.info(f"[{PLUGIN_NAME}] Loaded {len(photographers)} photographers from {csv_path}")
    return photographers


# Module-level database — loaded once on import
_PHOTOGRAPHER_DB: List[Dict[str, Any]] = _load_photographers_from_csv(_CSV_PATH)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_photographer_summary(p: Dict[str, Any]) -> Dict[str, Any]:
    """Return a clean serialisable photographer summary."""
    return {
        "photographer_id": p["id"],
        "name":            p["name"],
        "city":            p["city"],
        "country":         p["country"],
        "specializes_in":  p["specializes_in"],
        "style":           p["style"],
        "packages":        p["packages"],
        "min_budget_local": p["min_budget_local"],
        "currency":         p.get("currency", "USD"),
        "max_budget_local":  p["max_budget_local"],
        "contact_email":   p["contact_email"],
        "website":         p["website"],
        "instagram":       p["instagram"],
        "description":     p["description"],
    }


def _score_photographer(p: Dict[str, Any], styles: List[str]) -> int:
    """Score by style match — higher is better."""
    p_styles = {s.lower().replace(" ", "_").replace("-", "_") for s in p["style"]}
    return sum(1 for s in styles if s.lower().replace(" ", "_") in p_styles)


# ---------------------------------------------------------------------------
# SMTP helper — sends booking request email to photographer
# ---------------------------------------------------------------------------

def _send_photographer_booking_email(
    photographer: Dict[str, Any],
    package_name: str,
    estimated_price: float,
    event_date: Optional[str],
    venue_name: Optional[str],
    requester_name: str,
    requester_phone: Optional[str],
) -> Dict[str, Any]:
    """
    Send a booking REQUEST email to the photographer's contact_email from the CSV.
    Uses certifi SSL and ASCII password normalisation.
    """
    recipient = photographer["contact_email"]
    cur       = photographer.get("currency", "USD")
    subject   = f"REQUEST TO BOOK — {photographer['name']} — Photography"

    body = f"""Dear {photographer['name']} Team,

⚠️  THIS IS A REQUEST TO BOOK — NOT A CONFIRMED RESERVATION.

I am writing on behalf of {requester_name} to formally request to book your photography services for an upcoming wedding. No booking is confirmed until you respond and both parties agree in writing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PHOTOGRAPHY BOOKING REQUEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Photographer      : {photographer['name']}
  City              : {photographer['city']}, {photographer['country']}
  Package Selected  : {package_name}
  Estimated Price   : {cur} {estimated_price:,.2f}
  Event Date        : {event_date or 'To be confirmed'}
  Venue             : {venue_name or 'To be confirmed'}
  Instagram         : {photographer.get('instagram', 'N/A')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REQUESTER CONTACT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Name              : {requester_name}
  Phone             : {requester_phone if requester_phone else 'Please reply to this email'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please reply to confirm your availability, share your portfolio link, and
advise on contract and deposit requirements.

Kind regards,
Wedding Planning with SAM — Automated Booking System
"""

    log.info(f"[{PLUGIN_NAME}] Sending photography booking request to {recipient} for {photographer['name']}")

    try:
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USERNAME", "samdevuser@gmail.com")
        smtp_pass = os.environ.get("SMTP_PASSWORD", "gxtm bdtg tbyh icvt")
        sender    = os.environ.get("SMTP_FROM_ADDRESS", smtp_user)

        # Strip non-ASCII chars (fixes non-breaking spaces in copy-pasted App Passwords)
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

        log.info(f"[{PLUGIN_NAME}] ✅ Photography booking request email sent to {recipient}")
        return {"status": "success", "recipient": recipient, "subject": subject}

    except Exception as exc:
        log.exception(f"[{PLUGIN_NAME}] Failed to send photography booking email: {exc}")
        return {"status": "error", "message": f"Failed to send email: {exc}"}


# ---------------------------------------------------------------------------
# Tool 1 — get_photography_packages
# ---------------------------------------------------------------------------

async def get_photography_packages(
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Return all available photography and videography package options
    with full descriptions. Always call this first to present packages
    to the user before they choose.
    """
    log_identifier = f"[{PLUGIN_NAME}:get_photography_packages]"
    log.info(f"{log_identifier} Returning all package options.")

    return {
        "status":   "success",
        "message":  "Here are the available wedding photography packages.",
        "packages": [
            {
                "id":          pkg["id"],
                "name":        pkg["name"],
                "photo_count": pkg["photo_count"],
                "includes_video": pkg["video"],
                "includes":    pkg["includes"],
                "price_note":  pkg["price_note"],
            }
            for pkg in PACKAGES.values()
        ],
        "styles_available": [
            {"id": "romantic",       "description": "Soft, dreamy, emotion-driven imagery."},
            {"id": "documentary",    "description": "Natural storytelling — real moments, unposed."},
            {"id": "candid",         "description": "Spontaneous, authentic, unscripted shots."},
            {"id": "fine_art",       "description": "Artistic, editorial, gallery-worthy images."},
            {"id": "cinematic",      "description": "Film-inspired, dramatic, motion-picture quality."},
            {"id": "editorial",      "description": "Fashion/magazine style — bold and polished."},
            {"id": "natural",        "description": "Organic light, minimal posing, earthy tones."},
            {"id": "traditional",    "description": "Classic posed portraits, timeless coverage."},
            {"id": "luxury",         "description": "High-end, opulent, premium production value."},
            {"id": "rustic",         "description": "Warm, relaxed, countryside aesthetic."},
            {"id": "bollywood",      "description": "Vibrant, colourful, dramatic Indian style."},
            {"id": "multicultural",  "description": "Expert coverage of mixed-tradition ceremonies."},
            {"id": "coastal",        "description": "Sun-drenched, breezy, open-sky compositions."},
        ],
        "budget_note": (
            "Packages are priced per photographer. Prices range from ~$1,000 "
            "for essential photo-only packages to $20,000+ for full cinematic coverage. "
            "Ask the user for their photography budget to narrow down options."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 2 — search_photographers
# ---------------------------------------------------------------------------

async def search_photographers(
    city: str,
    package_preference: str,
    budget_usd: Optional[float] = None,
    style_preferences: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Search for wedding photographers matching city, package, budget, and style.

    Args:
        city:               Required. City of the wedding (e.g. 'London', 'Tokyo').
        package_preference: Required. One of: photos_only_300, photos_only_500,
                            photos_and_video, full_cinematic.
        budget_usd:         Optional. Maximum total budget in USD.
        style_preferences:  Optional. Comma-separated style preferences
                            (e.g. 'romantic,candid' or 'cinematic,luxury').
        tool_context:       Injected by SAM runtime.
        tool_config:        Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:search_photographers]"
    log.info(
        f"{log_identifier} city={city!r} package={package_preference!r} "
        f"budget={budget_usd} styles={style_preferences!r}"
    )

    # ── Validation ──────────────────────────────────────────────────────────
    if not city or not city.strip():
        return {"status": "error", "message": "city must not be empty."}

    if package_preference not in PACKAGES:
        return {
            "status":  "error",
            "message": (
                f"Invalid package_preference '{package_preference}'. "
                f"Valid values: {list(PACKAGES.keys())}"
            ),
        }

    requested_styles: List[str] = []
    if style_preferences:
        requested_styles = [
            s.strip().lower().replace(" ", "_").replace("-", "_")
            for s in style_preferences.split(",") if s.strip()
        ]

    # ── Filter ───────────────────────────────────────────────────────────────
    results: List[Dict[str, Any]] = []

    for p in _PHOTOGRAPHER_DB:

        # City filter
        if city.strip().lower() not in p["city"].lower():
            continue

        # Package availability filter
        if package_preference not in p["packages"]:
            continue

        # Budget filter — check against max_budget (upper bound of their pricing)
        if budget_usd is not None and p["min_budget_local"] > budget_usd:
            continue

        summary = _safe_photographer_summary(p)
        summary["match_score"] = _score_photographer(p, requested_styles)
        results.append(summary)

    # Sort by match_score desc, then min_budget asc
    results.sort(key=lambda p: (-p["match_score"], p["min_budget_local"]))

    log.info(f"{log_identifier} Found {len(results)} matching photographer(s).")
    return {
        "status":        "success",
        "message":       f"Found {len(results)} photographer(s) in {city} offering the '{PACKAGES[package_preference]['name']}' package.",
        "total_results": len(results),
        "photographers": results,
        "package_selected": PACKAGES[package_preference],
        "search_criteria": {
            "city":               city,
            "package_preference": package_preference,
            "budget_usd":         budget_usd,
            "style_preferences":  requested_styles or None,
        },
    }


# ---------------------------------------------------------------------------
# Tool 3 — get_photographer_details
# ---------------------------------------------------------------------------

async def get_photographer_details(
    photographer_id: str,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Retrieve full details for a specific photographer by ID (e.g. 'P001').

    Args:
        photographer_id: Required. The photographer identifier.
        tool_context:    Injected by SAM runtime.
        tool_config:     Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:get_photographer_details]"
    log.info(f"{log_identifier} photographer_id={photographer_id!r}")

    if not photographer_id or not photographer_id.strip():
        return {"status": "error", "message": "photographer_id must not be empty."}

    photographer_id = photographer_id.strip().upper()

    for p in _PHOTOGRAPHER_DB:
        if p["id"] == photographer_id:
            summary = _safe_photographer_summary(p)
            # Enrich with full package details
            summary["package_details"] = [
                PACKAGES[pkg] for pkg in p["packages"] if pkg in PACKAGES
            ]
            log.info(f"{log_identifier} Found: {p['name']}")
            return {
                "status":       "success",
                "message":      f"Photographer '{p['name']}' retrieved successfully.",
                "photographer": summary,
            }

    log.warning(f"{log_identifier} Photographer not found: {photographer_id!r}")
    return {
        "status":  "error",
        "message": (
            f"No photographer found with ID '{photographer_id}'. "
            f"Valid IDs: {[p['id'] for p in _PHOTOGRAPHER_DB]}"
        ),
    }


# ---------------------------------------------------------------------------
# Tool 4 — get_photography_quote
# ---------------------------------------------------------------------------

async def get_photography_quote(
    photographer_id: str,
    package_id: str,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate a detailed photography/videography quote for a specific
    photographer and package combination.

    Args:
        photographer_id: Required. Photographer identifier (e.g. 'P001').
        package_id:      Required. Package ID — one of:
                         photos_only_300, photos_only_500,
                         photos_and_video, full_cinematic.
        tool_context:    Injected by SAM runtime.
        tool_config:     Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:get_photography_quote]"
    log.info(
        f"{log_identifier} photographer_id={photographer_id!r} package_id={package_id!r}"
    )

    if not photographer_id or not photographer_id.strip():
        return {"status": "error", "message": "photographer_id must not be empty."}

    if package_id not in PACKAGES:
        return {
            "status":  "error",
            "message": (
                f"Invalid package_id '{package_id}'. "
                f"Valid values: {list(PACKAGES.keys())}"
            ),
        }

    photographer_id = photographer_id.strip().upper()

    for p in _PHOTOGRAPHER_DB:
        if p["id"] != photographer_id:
            continue

        if package_id not in p["packages"]:
            return {
                "status":  "error",
                "message": (
                    f"'{p['name']}' does not offer the '{PACKAGES[package_id]['name']}' package. "
                    f"Available packages: {p['packages']}"
                ),
            }

        pkg = PACKAGES[package_id]

        # Price estimate — use midpoint of photographer's range
        mid_price = round((p["min_budget_local"] + p["max_budget_local"]) / 2, 2)

        # Adjust for package tier
        multipliers = {
            "photos_only_300": 0.6,
            "photos_only_500": 0.8,
            "photos_and_video": 1.0,
            "full_cinematic":   1.4,
        }
        estimated_price = round(mid_price * multipliers.get(package_id, 1.0), 2)
        # Clamp within photographer's stated range
        estimated_price = max(p["min_budget_local"], min(p["max_budget_local"], estimated_price))

        log.info(
            f"{log_identifier} Quote: {p['name']} + {pkg['name']} = ${estimated_price:,.2f}"
        )
        return {
            "status":  "success",
            "message": (
                f"Quote for '{p['name']}' — {pkg['name']}: "
                f"estimated ${estimated_price:,.2f}."
            ),
            "quote": {
                "photographer_id":   p["id"],
                "photographer_name": p["name"],
                "city":              p["city"],
                "country":           p["country"],
                "style":             p["style"],
                "instagram":         p["instagram"],
                "package_id":        pkg["id"],
                "package_name":      pkg["name"],
                "photo_count":       pkg["photo_count"],
                "includes_video":    pkg["video"],
                "what_is_included":  pkg["includes"],
                "price_note":        pkg["price_note"],
                "estimated_price":   estimated_price,
                "price_range":       f"{p.get('currency','')}{p['min_budget_local']:,.0f} – {p.get('currency','')}{p['max_budget_local']:,.0f}",
                "contact_email":     p["contact_email"],
                "website":           p["website"],
                "next_steps": (
                    "Contact the photographer to discuss your specific requirements, "
                    "confirm availability on your wedding date, and review their portfolio. "
                    "A 25–30% deposit is typically required to secure the date."
                ),
            },
        }

    log.warning(f"{log_identifier} Photographer not found: {photographer_id!r}")
    return {
        "status":  "error",
        "message": f"No photographer found with ID '{photographer_id}'.",
    }


# ---------------------------------------------------------------------------
# Tool 5 — save_photography_quote_report
# ---------------------------------------------------------------------------

async def save_photography_quote_report(
    filename: str,
    photographer_id: str,
    package_id: str,
    requester_name: str = "Wedding Planning Guest",
    requester_phone: Optional[str] = None,
    event_date: Optional[str] = None,
    venue_name: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate a photography quote, save it as a text report artifact,
    and send a booking REQUEST email to the photographer's contact email.
    This is a REQUEST only — not a confirmed booking.

    Args:
        filename:         Required. Desired output filename.
        photographer_id:  Required. Photographer identifier.
        package_id:       Required. Package ID.
        requester_name:   Required. Full name — collect from user before calling.
        requester_phone:  Required. Phone number — collect from user before calling.
        event_date:       Optional. Wedding date (YYYY-MM-DD).
        venue_name:       Optional. Name of the wedding venue.
        tool_context:     Injected by SAM runtime.
        tool_config:      Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:save_photography_quote_report]"
    log.info(f"{log_identifier} filename='{filename}'")

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
                ("app_name", app_name), ("user_id", user_id),
                ("session_id", session_id), ("artifact_service", artifact_service),
            ] if not val
        ]
        return {
            "status":  "error",
            "message": f"Missing required context parts: {', '.join(missing)}",
        }

    # ── Generate quote ──────────────────────────────────────────────────────
    quote_result = await get_photography_quote(
        photographer_id=photographer_id,
        package_id=package_id,
        tool_context=tool_context,
        tool_config=tool_config,
    )

    if quote_result.get("status") == "error":
        return quote_result

    q         = quote_result["quote"]
    timestamp = datetime.now(timezone.utc)

    lines = [
        "=" * 70,
        "WEDDING PHOTOGRAPHY QUOTE REPORT",
        f"Generated : {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 70,
        "",
        "PHOTOGRAPHER DETAILS",
        "-" * 40,
        f"  Photographer   : {q['photographer_name']} ({q['photographer_id']})",
        f"  City           : {q['city']}, {q['country']}",
        f"  Style          : {', '.join(q['style'])}",
        f"  Instagram      : {q['instagram']}",
        f"  Contact Email  : {q['contact_email']}",
        f"  Website        : {q['website']}",
        "",
        "SELECTED PACKAGE",
        "-" * 40,
        f"  Package        : {q['package_name']}",
        f"  Photos         : {q['photo_count']}+ edited images",
        f"  Includes Video : {'Yes' if q['includes_video'] else 'No'}",
        "",
        "WHAT IS INCLUDED",
        "-" * 40,
    ]
    for item in q["what_is_included"]:
        lines.append(f"  ✓  {item}")

    lines += [
        "",
        "PRICING",
        "-" * 40,
        f"  Estimated Price : ${q['estimated_price']:,.2f}",
        f"  Price Range     : {q['price_range']}",
        f"  Note            : {q['price_note']}",
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
        "description":            f"Wedding photography quote report generated by {PLUGIN_NAME}.",
        "source_tool":            "save_photography_quote_report",
        "photographer_id":        photographer_id,
        "package_id":             package_id,
        "estimated_price":        q["estimated_price"],
        "creation_timestamp_iso": timestamp.isoformat(),
    }

    try:
        save_result = await save_artifact_with_metadata(
            artifact_service=artifact_service,
            app_name=app_name, user_id=user_id, session_id=session_id,
            filename=output_filename, content_bytes=content_bytes,
            mime_type="text/plain", metadata_dict=metadata_dict,
            timestamp=timestamp, schema_max_keys=DEFAULT_SCHEMA_MAX_KEYS,
            tool_context=tool_context,
        )
        if save_result.get("status") == "error":
            return {
                "status":  "error",
                "message": f"Failed to save artifact: {save_result.get('message')}",
            }

        log.info(
            f"{log_identifier} Report '{output_filename}' "
            f"v{save_result['data_version']} saved."
        )

        # Send booking request email to photographer's contact_email from CSV
        photographer_obj = next(
            (p for p in _PHOTOGRAPHER_DB if p["id"] == photographer_id.strip().upper()),
            None
        )
        email_sent_to = "unknown"
        email_note    = "Email not sent — photographer not found in database."
        if photographer_obj:
            email_result = _send_photographer_booking_email(
                photographer=photographer_obj,
                package_name=q["package_name"],
                estimated_price=q["estimated_price"],
                event_date=event_date,
                venue_name=venue_name,
                requester_name=requester_name,
                requester_phone=requester_phone,
            )
            email_sent_to = email_result.get("recipient", photographer_obj["contact_email"])
            email_note = (
                f"Booking request email sent to {email_sent_to}."
                if email_result.get("status") == "success"
                else f"Email error: {email_result.get('message', 'unknown')}"
            )

        return {
            "status":          "success",
            "message":         f"Photography quote saved. Estimated price: {q['estimated_price']:,.2f}. {email_note}",
            "output_filename": output_filename,
            "output_version":  save_result["data_version"],
            "estimated_price": q["estimated_price"],
            "email_sent_to":   email_sent_to,
            "requester_name":  requester_name,
            "requester_phone": requester_phone,
            "agent_response": (
                f"✅ A **booking request** for {q['photographer_name']} has been sent to "
                f"{email_sent_to} on your behalf.\n\n"
                f"⚠️ This is a **request only** — NOT confirmed until the photographer replies "
                f"and both parties agree in writing.\n\n"
                f"🎊 Your entire wedding is now planned! Venue, catering, decorations, "
                f"and photography booking requests have all been sent. Congratulations!"
            ),
        }
    except Exception as exc:
        log.exception(f"{log_identifier} Unexpected error: {exc}")
        return {
            "status":  "error",
            "message": f"An unexpected error occurred: {exc}",
        }


# ---------------------------------------------------------------------------
# Standalone test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def run_tests():
        print("=" * 70)
        print("PHOTO AGENT — STANDALONE TESTS")
        print("=" * 70)
        print(f"\nCSV path  : {_CSV_PATH}")
        print(f"Loaded    : {len(_PHOTOGRAPHER_DB)} photographers")

        class MockArtifactService:
            async def save_artifact(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}", "version": 1}
            async def save_artifact_metadata(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}.meta", "version": 1}

        class MockInvocationContext:
            def __init__(self):
                self.app_name         = "test_photo_app"
                self.user_id          = "test_user"
                self.session_id       = "test_session_001"
                self.artifact_service = MockArtifactService()

        class MockToolContext:
            def __init__(self):
                self._invocation_context = MockInvocationContext()

        ctx = MockToolContext()

        # Test 1: get packages
        print("\n--- Test 1: get_photography_packages ---")
        r1 = await get_photography_packages(tool_context=ctx)
        print(f"Status: {r1['status']} | Packages: {len(r1['packages'])}")
        for pkg in r1["packages"]:
            print(f"  • {pkg['name']} | Video: {pkg['includes_video']} | Photos: {pkg['photo_count']}")

        # Test 2: search London cinematic
        print("\n--- Test 2: search London full_cinematic (romantic,luxury) ---")
        r2 = await search_photographers(
            city="London", package_preference="full_cinematic",
            budget_usd=12000, style_preferences="romantic,luxury", tool_context=ctx
        )
        print(f"Status: {r2['status']} | Found: {r2.get('total_results', 0)}")
        for p in r2.get("photographers", []):
            print(f"  • {p['name']} [{p['photographer_id']}] score={p['match_score']}")

        # Test 3: search Mumbai photos_and_video
        print("\n--- Test 3: search Mumbai photos_and_video (bollywood) ---")
        r3 = await search_photographers(
            city="Mumbai", package_preference="photos_and_video",
            style_preferences="bollywood,cinematic", tool_context=ctx
        )
        print(f"Status: {r3['status']} | Found: {r3.get('total_results', 0)}")
        for p in r3.get("photographers", []):
            print(f"  • {p['name']} | {', '.join(p['style'][:2])}")

        # Test 4: get quote
        print("\n--- Test 4: get_photography_quote (P001, full_cinematic) ---")
        r4 = await get_photography_quote(
            photographer_id="P001", package_id="full_cinematic", tool_context=ctx
        )
        print(f"Status: {r4['status']}")
        if r4["status"] == "success":
            q = r4["quote"]
            print(f"Photographer : {q['photographer_name']}")
            print(f"Package      : {q['package_name']}")
            print(f"Est. Price   : ${q['estimated_price']:,.2f}")
            print(f"Video        : {q['includes_video']}")

        # Test 5: save report
        print("\n--- Test 5: save_photography_quote_report ---")
        r5 = await save_photography_quote_report(
            filename="london_photo_quote", photographer_id="P001",
            package_id="full_cinematic", tool_context=ctx
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