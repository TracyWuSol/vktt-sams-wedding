"""
Wedding Venue Agent Tools — v3
Reads venues from venues.csv, validates dates are not in the past,
sends real SMTP booking REQUEST emails (not dev/simulation mode).
"""

import csv
import logging
import asyncio
import os
import smtplib
import ssl
import certifi
from datetime import datetime, date, timedelta, timezone
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

PLUGIN_NAME = "wedding_venue_agent"

# ---------------------------------------------------------------------------
# CSV path — place venues.csv alongside this file:
#   wedding-venue-agent/src/wedding_venue_agent/venues.csv
# ---------------------------------------------------------------------------

_CSV_PATH = Path(__file__).parent / "venues.csv"

# ---------------------------------------------------------------------------
# Dashboard integration
# ---------------------------------------------------------------------------

WEDDING_DASHBOARD_URL: str = os.environ.get(
    "WEDDING_DASHBOARD_URL",
    "http://localhost:8000/wedding_dashboard.html",
)


def _dashboard_link(extra_msg: str = "") -> str:
    """Return a persistent dashboard link to append to EVERY agent response."""
    return (
        f"\n\n---\n"
        f"📊 **[View Your Wedding Planning Dashboard]({WEDDING_DASHBOARD_URL})** "
        f"— track venues, catering, decorations & photography in one place.\n"
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
# Valid option sets
# ---------------------------------------------------------------------------

VALID_WEDDING_FUNCTIONS = {
    "ceremony", "reception", "ceremony_and_reception",
    "rehearsal_dinner", "bridal_shower", "engagement_party",
}

VALID_VENUE_TYPES = {
    "hotel", "banquet_hall", "garden", "beach",
    "mansion", "restaurant", "country_club", "museum",
}

VALID_SETTINGS = {"indoor", "outdoor", "both"}

# ---------------------------------------------------------------------------
# CSV loader — supports both local-currency and USD column names
# ---------------------------------------------------------------------------

def _load_venues_from_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Load and parse venues from the CSV file into a list of dicts."""
    if not csv_path.exists():
        log.error(f"[{PLUGIN_NAME}] venues.csv not found at {csv_path}")
        return []

    venues: List[Dict[str, Any]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # Support both local-currency columns (venues_local.csv) and
                # original USD columns (venues.csv) so either file works.
                base_col  = "base_price_local"      if "base_price_local"      in row else "base_price_usd"
                guest_col = "price_per_guest_local"  if "price_per_guest_local"  in row else "price_per_guest_usd"
                venue = {
                    "id":                  row["venue_id"].strip(),
                    "name":                row["name"].strip(),
                    "city":                row["city"].strip(),
                    "country":             row["country"].strip(),
                    "venue_type":          row["venue_type"].strip().lower(),
                    "setting":             row["setting"].strip().lower(),
                    "address":             row["address"].strip(),
                    "capacity_min":        int(row["capacity_min"]),
                    "capacity_max":        int(row["capacity_max"]),
                    "base_price":          float(row[base_col]),
                    "price_per_guest":     float(row[guest_col]),
                    "currency":            row.get("currency", "USD").strip(),
                    "supported_functions": [f.strip() for f in row["supported_functions"].split(",")],
                    "amenities":           [a.strip() for a in row["amenities"].split(",")],
                    "description":         row["description"].strip(),
                    "contact_email":       row["contact_email"].strip(),
                    "website":             row["website"].strip(),
                    "booked_dates": set(
                        d.strip()
                        for d in row.get("booked_dates", "").split("|")
                        if d.strip()
                    ),
                }
                venues.append(venue)
            except (KeyError, ValueError) as exc:
                log.warning(f"[{PLUGIN_NAME}] Skipping malformed CSV row: {exc} — {row}")

    log.info(f"[{PLUGIN_NAME}] Loaded {len(venues)} venues from {csv_path}")
    return venues


# Module-level venue database — loaded once on import
_VENUE_DB: List[Dict[str, Any]] = _load_venues_from_csv(_CSV_PATH)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_date(date_str: str) -> Optional[date]:
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_past_date(date_str: str) -> bool:
    d = _parse_date(date_str)
    return d is not None and d < _today()


def _venue_is_available(venue: Dict[str, Any], date_str: str) -> bool:
    return date_str not in venue["booked_dates"]


def _venue_estimated_cost(venue: Dict[str, Any], guest_count: int) -> float:
    return venue["base_price"] + venue["price_per_guest"] * guest_count


def _safe_venue_summary(venue: Dict[str, Any], match_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "venue_id":            venue["id"],
        "name":                venue["name"],
        "city":                venue["city"],
        "country":             venue["country"],
        "venue_type":          venue["venue_type"],
        "setting":             venue["setting"],
        "address":             venue["address"],
        "capacity_min":        venue["capacity_min"],
        "capacity_max":        venue["capacity_max"],
        "base_price":          venue["base_price"],
        "price_per_guest":     venue["price_per_guest"],
        "currency":            venue.get("currency", "USD"),
        "supported_functions": venue["supported_functions"],
        "amenities":           venue["amenities"],
        "description":         venue["description"],
        "contact_email":       venue["contact_email"],
        "website":             venue["website"],
        "estimated_cost":      match_info.get("estimated_cost"),
        "within_budget":       match_info.get("within_budget"),
        "availability_dates":  match_info.get("availability_dates", []),
    }


def _send_booking_email(
    venue: Dict[str, Any],
    guest_count: int,
    event_date: str,
    event_type: str,
    requester_name: str = "Wedding Planning Guest",
    requester_phone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send a booking REQUEST email via SMTP.
    Uses certifi for SSL and strips non-ASCII chars from the password.
    """
    recipient = venue["contact_email"]
    subject   = f"REQUEST TO BOOK — {venue['name']} — {event_date}"

    body = f"""Dear {venue['name']} Events Team,

⚠️  THIS IS A REQUEST TO BOOK — NOT A CONFIRMED RESERVATION.

I am writing on behalf of {requester_name} to formally request to book your venue for the following wedding event. No reservation is confirmed until you respond and both parties agree in writing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VENUE BOOKING REQUEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Venue           : {venue['name']}
  Address         : {venue['address']}
  City            : {venue['city']}, {venue['country']}
  Event Date      : {event_date}
  Event Type      : {event_type.replace('_', ' ').title()}
  Guest Count     : {guest_count} guests
  Estimated Cost  : {venue.get('currency','USD')} {_venue_estimated_cost(venue, guest_count):,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REQUESTER CONTACT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Name            : {requester_name}
  Phone           : {requester_phone if requester_phone else 'Please reply to this email'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please reply to confirm availability, share your contract, and advise on deposit requirements.

Kind regards,
Wedding Planning with SAM — Automated Booking System
"""

    log.info(
        f"[{PLUGIN_NAME}:send_booking_email] "
        f"Sending booking request to {recipient} for {venue['name']} on {event_date}"
    )

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

        log.info(f"[{PLUGIN_NAME}] ✅ Booking request email sent to {recipient}: {subject}")
        return {
            "status":    "success",
            "recipient": recipient,
            "subject":   subject,
            "body":      body,
        }

    except Exception as exc:
        log.exception(f"[{PLUGIN_NAME}] Failed to send booking request email: {exc}")
        return {
            "status":  "error",
            "message": f"Failed to send email: {exc}",
        }


# ---------------------------------------------------------------------------
# Tool 1 — search_venues
# ---------------------------------------------------------------------------

async def search_venues(
    start_date: str,
    end_date: Optional[str] = None,
    budget: Optional[float] = None,
    guest_count: Optional[int] = None,
    function_type: Optional[str] = None,
    venue_types: Optional[str] = None,
    setting: Optional[str] = None,
    city: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Search for available wedding venues from the global CSV database.

    Args:
        start_date:    Required. Event date or range start (YYYY-MM-DD). Must not be in the past.
        end_date:      Optional. Range end date (YYYY-MM-DD).
        budget:        Optional. Max total budget in local currency.
        guest_count:   Optional. Expected number of guests.
        function_type: Optional. One of: ceremony, reception, ceremony_and_reception,
                       rehearsal_dinner, bridal_shower, engagement_party.
        venue_types:   Optional. Comma-separated: hotel, banquet_hall, garden,
                       beach, mansion, restaurant, country_club, museum.
        setting:       Optional. 'indoor', 'outdoor', or 'both'.
        city:          Optional. City name (e.g. 'London', 'Tokyo', 'Mumbai', 'Paris').
        tool_context:  Injected by SAM runtime.
        tool_config:   Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:search_venues]"
    log.info(f"{log_identifier} start_date={start_date!r} city={city!r} guest_count={guest_count}")

    start = _parse_date(start_date)
    if start is None:
        return {"status": "error", "message": f"Invalid start_date format: '{start_date}'. Expected YYYY-MM-DD."}

    if _is_past_date(start_date):
        return {"status": "error", "message": f"The date '{start_date}' is in the past. Please provide a future date (today is {_today()})."}

    if end_date:
        if _parse_date(end_date) is None:
            return {"status": "error", "message": f"Invalid end_date format: '{end_date}'. Expected YYYY-MM-DD."}
        if _is_past_date(end_date):
            return {"status": "error", "message": f"The end_date '{end_date}' is in the past."}

    if function_type and function_type not in VALID_WEDDING_FUNCTIONS:
        return {"status": "error", "message": f"Invalid function_type '{function_type}'. Valid: {sorted(VALID_WEDDING_FUNCTIONS)}"}

    requested_venue_types: List[str] = []
    if venue_types:
        requested_venue_types = [v.strip().lower() for v in venue_types.split(",") if v.strip()]
        invalid_vt = [v for v in requested_venue_types if v not in VALID_VENUE_TYPES]
        if invalid_vt:
            return {"status": "error", "message": f"Invalid venue_type(s): {invalid_vt}. Valid: {sorted(VALID_VENUE_TYPES)}"}

    if setting and setting.lower() not in VALID_SETTINGS:
        return {"status": "error", "message": f"Invalid setting '{setting}'. Valid: indoor, outdoor, both."}

    dates_to_check: List[str] = [start_date]
    if end_date:
        cur   = start
        end_d = _parse_date(end_date)
        while cur <= end_d:
            ds = cur.strftime("%Y-%m-%d")
            if ds not in dates_to_check:
                dates_to_check.append(ds)
            cur += timedelta(days=1)

    results: List[Dict[str, Any]] = []

    for venue in _VENUE_DB:
        match_info: Dict[str, Any] = {"estimated_cost": None, "within_budget": None, "availability_dates": []}

        if city and city.strip().lower() not in venue["city"].lower():
            continue
        if function_type and function_type not in venue["supported_functions"]:
            continue
        if requested_venue_types and venue["venue_type"] not in requested_venue_types:
            continue
        if setting and setting.lower() != "both":
            if venue["setting"] != setting.lower():
                continue
        if guest_count is not None:
            if not (venue["capacity_min"] <= guest_count <= venue["capacity_max"]):
                continue
            match_info["estimated_cost"] = _venue_estimated_cost(venue, guest_count)
        if budget is not None and match_info["estimated_cost"] is not None:
            match_info["within_budget"] = match_info["estimated_cost"] <= budget
            if not match_info["within_budget"]:
                continue

        available_dates = [d for d in dates_to_check if _venue_is_available(venue, d)]
        if not available_dates:
            continue

        match_info["availability_dates"] = available_dates
        results.append(_safe_venue_summary(venue, match_info))

    results.sort(key=lambda v: (v["estimated_cost"] is None, v["estimated_cost"] or 0, v["name"]))

    log.info(f"{log_identifier} Found {len(results)} matching venue(s).")
    return {
        "status":        "success",
        "message":       f"Found {len(results)} available venue(s) matching your criteria.",
        "total_results": len(results),
        "venues":        results,
        "search_criteria": {
            "start_date": start_date, "end_date": end_date, "city": city,
            "budget": budget, "guest_count": guest_count,
            "function_type": function_type,
            "venue_types": requested_venue_types or None,
            "setting": setting,
        },
    }


# ---------------------------------------------------------------------------
# Tool 2 — get_venue_details
# ---------------------------------------------------------------------------

async def get_venue_details(
    venue_id: str,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retrieve full details for a single venue by its ID (e.g. 'V001')."""
    log_identifier = f"[{PLUGIN_NAME}:get_venue_details]"
    log.info(f"{log_identifier} venue_id={venue_id!r}")

    if not venue_id or not venue_id.strip():
        return {"status": "error", "message": "venue_id must not be empty."}

    venue_id = venue_id.strip().upper()

    for venue in _VENUE_DB:
        if venue["id"] == venue_id:
            return {
                "status":  "success",
                "message": f"Venue '{venue['name']}' retrieved successfully.",
                "venue": {
                    "venue_id": venue["id"], "name": venue["name"],
                    "city": venue["city"], "country": venue["country"],
                    "venue_type": venue["venue_type"], "setting": venue["setting"],
                    "address": venue["address"],
                    "capacity_min": venue["capacity_min"], "capacity_max": venue["capacity_max"],
                    "base_price": venue["base_price"], "price_per_guest": venue["price_per_guest"],
                    "currency": venue.get("currency", "USD"),
                    "supported_functions": venue["supported_functions"],
                    "amenities": venue["amenities"], "description": venue["description"],
                    "contact_email": venue["contact_email"], "website": venue["website"],
                    "known_booked_dates": sorted(venue["booked_dates"]),
                },
            }

    return {"status": "error", "message": f"No venue found with ID '{venue_id}'. Valid IDs: {[v['id'] for v in _VENUE_DB]}"}


# ---------------------------------------------------------------------------
# Tool 3 — check_venue_availability
# ---------------------------------------------------------------------------

async def check_venue_availability(
    venue_id: str,
    date: str,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Check whether a specific venue is available on a given future date."""
    if not venue_id or not venue_id.strip():
        return {"status": "error", "message": "venue_id must not be empty."}
    if _parse_date(date) is None:
        return {"status": "error", "message": f"Invalid date format: '{date}'. Expected YYYY-MM-DD."}
    if _is_past_date(date):
        return {"status": "error", "message": f"The date '{date}' is in the past. Please provide a future date."}

    venue_id = venue_id.strip().upper()
    for venue in _VENUE_DB:
        if venue["id"] == venue_id:
            is_available = _venue_is_available(venue, date)
            return {
                "status":       "success",
                "message":      f"'{venue['name']}' is {'available' if is_available else 'NOT available'} on {date}.",
                "venue_id":     venue["id"],
                "venue_name":   venue["name"],
                "date":         date,
                "is_available": is_available,
            }

    return {"status": "error", "message": f"No venue found with ID '{venue_id}'."}


# ---------------------------------------------------------------------------
# Tool 4 — get_venue_quote
# ---------------------------------------------------------------------------

async def get_venue_quote(
    venue_id: str,
    guest_count: int,
    function_type: str,
    event_date: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a detailed pricing quote for a wedding venue."""
    if not venue_id or not venue_id.strip():
        return {"status": "error", "message": "venue_id must not be empty."}
    if not isinstance(guest_count, int) or guest_count <= 0:
        return {"status": "error", "message": f"guest_count must be a positive integer, got {guest_count!r}."}
    if function_type not in VALID_WEDDING_FUNCTIONS:
        return {"status": "error", "message": f"Invalid function_type '{function_type}'. Valid: {sorted(VALID_WEDDING_FUNCTIONS)}"}
    if event_date:
        if _parse_date(event_date) is None:
            return {"status": "error", "message": f"Invalid event_date format: '{event_date}'. Expected YYYY-MM-DD."}
        if _is_past_date(event_date):
            return {"status": "error", "message": f"The event_date '{event_date}' is in the past."}

    venue_id = venue_id.strip().upper()
    for venue in _VENUE_DB:
        if venue["id"] != venue_id:
            continue
        if function_type not in venue["supported_functions"]:
            return {"status": "error", "message": f"'{venue['name']}' does not support '{function_type}'. Supported: {venue['supported_functions']}"}
        if not (venue["capacity_min"] <= guest_count <= venue["capacity_max"]):
            return {"status": "error", "message": f"Guest count {guest_count} is outside '{venue['name']}' capacity ({venue['capacity_min']}–{venue['capacity_max']})."}

        estimated_total = _venue_estimated_cost(venue, guest_count)
        cur = venue.get("currency", "USD")
        return {
            "status":  "success",
            "message": f"Quote for '{venue['name']}' — estimated total {cur} {estimated_total:,.2f} for {guest_count} guests.",
            "quote": {
                "venue_id": venue["id"], "venue_name": venue["name"],
                "city": venue["city"], "country": venue["country"],
                "venue_type": venue["venue_type"], "setting": venue["setting"],
                "address": venue["address"], "function_type": function_type,
                "event_date": event_date, "guest_count": guest_count,
                "base_price": venue["base_price"], "price_per_guest": venue["price_per_guest"],
                "currency": cur, "estimated_total": estimated_total,
                "amenities_included": venue["amenities"],
                "contact_email": venue["contact_email"], "website": venue["website"],
                "next_steps": (
                    "To send a booking request, say 'book this venue'. "
                    "I will ask for your name and phone number, then send a request email. "
                    "⚠️ The booking is NOT confirmed until the venue replies."
                ),
            },
        }

    return {"status": "error", "message": f"No venue found with ID '{venue_id}'."}


# ---------------------------------------------------------------------------
# Tool 5 — request_venue_booking
# ---------------------------------------------------------------------------

async def request_venue_booking(
    venue_id: str,
    guest_count: int,
    event_date: str,
    event_type: str,
    requester_name: str = "Wedding Planning Guest",
    requester_phone: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Send a booking REQUEST email to the venue's contact.
    This is a REQUEST only — NOT a confirmed booking.
    Always collect requester_name and requester_phone before calling this.

    Args:
        venue_id:        Required. Venue identifier (e.g. 'V007').
        guest_count:     Required. Number of guests.
        event_date:      Required. Event date (YYYY-MM-DD). Must not be in the past.
        event_type:      Required. Type of event (e.g. 'ceremony_and_reception').
        requester_name:  Required. Full name — collect from user before calling.
        requester_phone: Required. Phone number — collect from user before calling.
        tool_context:    Injected by SAM runtime.
        tool_config:     Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:request_venue_booking]"
    log.info(f"{log_identifier} venue_id={venue_id!r} guest_count={guest_count} event_date={event_date!r}")

    if not venue_id or not venue_id.strip():
        return {"status": "error", "message": "venue_id must not be empty."}
    if not isinstance(guest_count, int) or guest_count <= 0:
        return {"status": "error", "message": f"guest_count must be a positive integer, got {guest_count!r}."}
    if _parse_date(event_date) is None:
        return {"status": "error", "message": f"Invalid event_date format: '{event_date}'. Expected YYYY-MM-DD."}
    if _is_past_date(event_date):
        return {"status": "error", "message": f"The event_date '{event_date}' is in the past."}

    venue_id = venue_id.strip().upper()

    target_venue: Optional[Dict[str, Any]] = None
    for venue in _VENUE_DB:
        if venue["id"] == venue_id:
            target_venue = venue
            break

    if target_venue is None:
        return {"status": "error", "message": f"No venue found with ID '{venue_id}'."}

    if not _venue_is_available(target_venue, event_date):
        return {
            "status":  "error",
            "message": f"'{target_venue['name']}' is already booked on {event_date}. Please choose a different date or venue.",
        }

    email_result = _send_booking_email(
        venue=target_venue,
        guest_count=guest_count,
        event_date=event_date,
        event_type=event_type,
        requester_name=requester_name or "Wedding Planning Guest",
        requester_phone=requester_phone,
    )

    if email_result["status"] != "success":
        return {
            "status":  "error",
            "message": f"Failed to send booking request email: {email_result.get('message')}",
        }

    log.info(f"{log_identifier} Booking request sent for {target_venue['name']} on {event_date} to {email_result['recipient']}")

    return {
        "status":          "success",
        "booking_sent":    True,
        "venue_id":        target_venue["id"],
        "venue_name":      target_venue["name"],
        "city":            target_venue["city"],
        "country":         target_venue["country"],
        "event_date":      event_date,
        "event_type":      event_type,
        "guest_count":     guest_count,
        "email_sent_to":   email_result["recipient"],
        "requester_name":  requester_name,
        "requester_phone": requester_phone,
        "message": (
            f"A booking REQUEST for '{target_venue['name']}' on {event_date} "
            f"has been sent to {email_result['recipient']}. "
            f"This is a request only — NOT a confirmed booking."
        ),
        "agent_response": (
            f"✅ A **booking request** for {target_venue['name']} has been sent to "
            f"{email_result['recipient']} on your behalf.\n\n"
            f"⚠️ **This is a request only — your booking is NOT confirmed** until "
            f"the venue responds and both parties agree in writing.\n\n"
            f"{target_venue['name']} will contact **{requester_name}** directly to confirm "
            f"availability, share the contract, and advise on the deposit.\n\n"
            f"Let's now find your caterer!"
            + _dashboard_link("Booking request sent — awaiting venue confirmation.")
        ),
        "dashboard_update": _dashboard_update_script(
            task_id="venue",
            vendor=target_venue["name"],
            city=target_venue["city"],
            chosen=True, emailed=True, booked=False,
        ),
    }


# ---------------------------------------------------------------------------
# Tool 6 — save_venue_search_report
# ---------------------------------------------------------------------------

async def save_venue_search_report(
    filename: str,
    start_date: str,
    end_date: Optional[str] = None,
    budget: Optional[float] = None,
    guest_count: Optional[int] = None,
    function_type: Optional[str] = None,
    venue_types: Optional[str] = None,
    city: Optional[str] = None,
    setting: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run a venue search and save the results as a text report artifact."""
    log_identifier = f"[{PLUGIN_NAME}:save_venue_search_report]"
    log.info(f"{log_identifier} filename='{filename}'")

    if not tool_context or not tool_context._invocation_context:
        return {"status": "error", "message": "ToolContext or InvocationContext is missing."}

    inv_context      = tool_context._invocation_context
    app_name         = getattr(inv_context, "app_name", None)
    user_id          = getattr(inv_context, "user_id", None)
    session_id       = get_original_session_id(inv_context)
    artifact_service = getattr(inv_context, "artifact_service", None)

    if not all([app_name, user_id, session_id, artifact_service]):
        missing = [label for label, val in [("app_name", app_name), ("user_id", user_id),
                   ("session_id", session_id), ("artifact_service", artifact_service)] if not val]
        return {"status": "error", "message": f"Missing required context parts: {', '.join(missing)}"}

    search_result = await search_venues(
        start_date=start_date, end_date=end_date, budget=budget,
        guest_count=guest_count, function_type=function_type,
        venue_types=venue_types, setting=setting, city=city,
        tool_context=tool_context, tool_config=tool_config,
    )

    if search_result.get("status") == "error":
        return search_result

    timestamp    = datetime.now(timezone.utc)
    venues_found = search_result.get("venues", [])
    criteria     = search_result.get("search_criteria", {})

    lines: List[str] = [
        "=" * 70, "WEDDING VENUE AVAILABILITY REPORT",
        f"Generated : {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 70, "",
        "SEARCH CRITERIA", "-" * 40,
        f"  City                : {criteria.get('city') or 'Any'}",
        f"  Start Date          : {criteria.get('start_date', 'N/A')}",
        f"  End Date            : {criteria.get('end_date') or 'N/A'}",
        f"  Budget              : {criteria['budget'] if criteria.get('budget') else 'N/A'}",
        f"  Guest Count         : {criteria.get('guest_count') or 'N/A'}",
        f"  Function Type       : {criteria.get('function_type') or 'Any'}",
        f"  Venue Types         : {', '.join(criteria['venue_types']) if criteria.get('venue_types') else 'Any'}",
        f"  Setting             : {criteria.get('setting') or 'Any'}",
        "", f"RESULTS  ({len(venues_found)} venue(s) found)", "=" * 70,
    ]

    for i, v in enumerate(venues_found, start=1):
        cost_str  = f"{v.get('currency','')}{v['estimated_cost']:,.2f}" if v["estimated_cost"] is not None else "N/A"
        avail_str = ", ".join(v["availability_dates"][:5])
        if len(v["availability_dates"]) > 5:
            avail_str += f" (+{len(v['availability_dates']) - 5} more)"
        lines += [
            "", f"[{i}] {v['name']}  ({v['venue_type'].replace('_',' ').title()} | {v['setting'].title()})",
            f"     ID              : {v['venue_id']}",
            f"     City            : {v['city']}, {v['country']}",
            f"     Address         : {v['address']}",
            f"     Capacity        : {v['capacity_min']}–{v['capacity_max']} guests",
            f"     Estimated Cost  : {cost_str}",
            f"     Available Dates : {avail_str}",
            f"     Description     : {v['description']}",
            f"     Amenities       : {', '.join(v['amenities'])}",
            f"     Contact Email   : {v['contact_email']}",
            f"     Website         : {v['website']}",
        ]

    lines += ["", "=" * 70, "END OF REPORT", "=" * 70]
    report_text = "\n".join(lines)

    output_filename = filename.strip()
    if not output_filename.lower().endswith(".txt"):
        output_filename += ".txt"

    try:
        save_result = await save_artifact_with_metadata(
            artifact_service=artifact_service,
            app_name=app_name, user_id=user_id, session_id=session_id,
            filename=output_filename, content_bytes=report_text.encode("utf-8"),
            mime_type="text/plain",
            metadata_dict={"description": f"Venue search report.", "source_tool": "save_venue_search_report",
                           "venues_found": len(venues_found), "creation_timestamp_iso": timestamp.isoformat()},
            timestamp=timestamp, schema_max_keys=DEFAULT_SCHEMA_MAX_KEYS,
            tool_context=tool_context,
        )
        if save_result.get("status") == "error":
            return {"status": "error", "message": f"Failed to save artifact: {save_result.get('message')}"}

        return {
            "status": "success",
            "message": f"Venue search report '{output_filename}' saved with {len(venues_found)} venue(s).",
            "output_filename": output_filename,
            "output_version":  save_result["data_version"],
            "venues_found":    len(venues_found),
        }
    except Exception as exc:
        log.exception(f"{log_identifier} Unexpected error: {exc}")
        return {"status": "error", "message": f"An unexpected error occurred: {exc}"}


# ---------------------------------------------------------------------------
# Standalone test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def run_tests():
        print("=" * 70)
        print("WEDDING VENUE AGENT v3 — STANDALONE TESTS")
        print("=" * 70)
        print(f"\nToday  : {_today()}")
        print(f"CSV    : {_CSV_PATH}")
        print(f"Venues : {len(_VENUE_DB)}")

        class MockArtifactService:
            async def save_artifact(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}", "version": 1}
            async def save_artifact_metadata(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}.meta", "version": 1}

        class MockInvocationContext:
            def __init__(self):
                self.app_name = "test_venue_app"
                self.user_id = "test_user"
                self.session_id = "test_session_001"
                self.artifact_service = MockArtifactService()

        class MockToolContext:
            def __init__(self):
                self._invocation_context = MockInvocationContext()

        ctx = MockToolContext()

        print("\n--- Test 1: Past date rejection ---")
        r1 = await search_venues(start_date="2023-01-01", city="London", tool_context=ctx)
        print(f"Status: {r1['status']} | {r1['message']}")

        print("\n--- Test 2: Search Mumbai ---")
        r2 = await search_venues(start_date="2026-09-01", city="Mumbai", tool_context=ctx)
        print(f"Status: {r2['status']} | Found: {r2.get('total_results', 0)}")
        for v in r2.get("venues", []):
            print(f"  • {v['name']} ({v['city']}) — {v.get('currency','')} {v['estimated_cost'] or 'N/A'}")

        print("\n--- Test 3: Search Tokyo ---")
        r3 = await search_venues(start_date="2026-09-01", city="Tokyo", tool_context=ctx)
        print(f"Status: {r3['status']} | Found: {r3.get('total_results', 0)}")
        for v in r3.get("venues", []):
            print(f"  • {v['name']} ({v['city']})")

        print("\n" + "=" * 70)
        print("All tests complete.")
        print("=" * 70)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    asyncio.run(run_tests())