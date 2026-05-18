"""
Wedding Email Agent Tools
Centralised email dispatch agent for all wedding booking confirmations.
Real SMTP email sending is ENABLED by default.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✏️  CONFIGURATION — UPDATE THESE VALUES BEFORE DEPLOYING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  All SMTP settings are defined in the CONFIG block below (lines 40–65).
  You MUST update the following before real emails will send:

    SMTP_USERNAME      ← your Gmail / Outlook address  (REQUIRED)
    SMTP_PASSWORD      ← your App Password             (REQUIRED)
    SMTP_FROM_ADDRESS  ← display sender address        (REQUIRED)

  Optional (defaults work for Gmail):
    SMTP_HOST          ← default: smtp.gmail.com
    SMTP_PORT          ← default: 587
    SMTP_USE_TLS       ← default: True (always recommended)

  Gmail users: generate an App Password at
    https://myaccount.google.com/apppasswords
  (requires 2-Step Verification to be enabled)

  Outlook/Office365 users:
    SMTP_HOST = smtp.office365.com, SMTP_PORT = 587

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import logging
import asyncio
import os
import smtplib
import ssl
import certifi
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from google.adk.tools import ToolContext
from solace_agent_mesh.agent.utils.artifact_helpers import (
    save_artifact_with_metadata,
    DEFAULT_SCHEMA_MAX_KEYS,
)
from solace_agent_mesh.agent.utils.context_helpers import get_original_session_id

log = logging.getLogger(__name__)

PLUGIN_NAME = "email_agent"

# ═══════════════════════════════════════════════════════════════════════════
#  ✏️  SMTP CONFIGURATION — UPDATE THE VALUES MARKED WITH  ← UPDATE THIS
# ═══════════════════════════════════════════════════════════════════════════

SMTP_CONFIG = {
    # ── Sender credentials ─────────────────────────────────────────────────
    "SMTP_USERNAME":     "samdevuser@gmail.com",           # ← UPDATE if changing sender
    "SMTP_PASSWORD":     "gxtm bdtg tbyh icvt",           # ← UPDATE if App Password changes
    "SMTP_FROM_ADDRESS": "samdevuser@gmail.com",           # ← UPDATE to match username

    # ── Server settings (defaults work for Gmail — change for Outlook etc) ─
    "SMTP_HOST":         "smtp.gmail.com",                # ← Outlook: smtp.office365.com
    "SMTP_PORT":         587,                             # ← Keep 587 for TLS (use 465 for SSL-only)
    "SMTP_USE_TLS":      True,                            # ← Always True recommended
}

# ─── Environment variable overrides ────────────────────────────────────────
# If you prefer to use environment variables instead of editing above,
# set any of: SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_ADDRESS,
#             SMTP_HOST, SMTP_PORT, SMTP_USE_TLS
# Environment variables take priority over the SMTP_CONFIG dict above.
# ───────────────────────────────────────────────────────────────────────────

def _get_smtp_config() -> Dict[str, Any]:
    """
    Merge SMTP_CONFIG defaults with environment variable overrides.
    Environment variables always take priority.
    """
    return {
        "host":      os.environ.get("SMTP_HOST",         SMTP_CONFIG["SMTP_HOST"]),
        "port":      int(os.environ.get("SMTP_PORT",     str(SMTP_CONFIG["SMTP_PORT"]))),
        "username":  os.environ.get("SMTP_USERNAME",     SMTP_CONFIG["SMTP_USERNAME"]),
        "password":  os.environ.get("SMTP_PASSWORD",     SMTP_CONFIG["SMTP_PASSWORD"]),
        "sender":    os.environ.get("SMTP_FROM_ADDRESS", SMTP_CONFIG["SMTP_FROM_ADDRESS"]),
        "use_tls":   os.environ.get("SMTP_USE_TLS",      str(SMTP_CONFIG["SMTP_USE_TLS"])).lower() != "false",
    }


def _validate_smtp_config(cfg: Dict[str, Any]) -> Optional[str]:
    """
    Validate that SMTP config has been filled in.
    Returns an error string if invalid, None if OK.
    """
    if not cfg["username"] or cfg["username"] in ("", "YOUR_EMAIL@gmail.com"):
        return (
            "SMTP_USERNAME is not configured. "
            "Please update SMTP_CONFIG in email_agent_tools.py or set the SMTP_USERNAME environment variable."
        )
    if not cfg["password"] or cfg["password"] in ("", "YOUR_APP_PASSWORD_HERE"):
        return (
            "SMTP_PASSWORD is not configured. "
            "Please update SMTP_CONFIG in email_agent_tools.py or set the SMTP_PASSWORD environment variable."
        )
    if not cfg["sender"] or cfg["sender"] in ("", "YOUR_EMAIL@gmail.com"):
        return (
            "SMTP_FROM_ADDRESS is not configured. "
            "Please update SMTP_CONFIG in email_agent_tools.py or set the SMTP_FROM_ADDRESS environment variable."
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Core email dispatch
# ═══════════════════════════════════════════════════════════════════════════

def _send_email(
    recipient: str,
    subject: str,
    body: str,
) -> Dict[str, Any]:
    """
    Send an email via SMTP using the configured credentials.
    Returns {"status": "success"|"error", "message": str, "simulated": False}.
    """
    cfg = _get_smtp_config()

    # Validate config before attempting send
    validation_error = _validate_smtp_config(cfg)
    if validation_error:
        log.error(f"[{PLUGIN_NAME}] SMTP configuration error: {validation_error}")
        return {
            "status":  "error",
            "message": validation_error,
        }

    log.info(
        f"[{PLUGIN_NAME}] Sending email to {recipient} via {cfg['host']}:{cfg['port']}"
    )

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Wedding Planning with SAM <{cfg['sender']}>"
        msg["To"]      = recipient
        msg.attach(MIMEText(body, "plain"))

        # certifi CA bundle — fixes macOS SSL certificate verification error
        tls_ctx = ssl.create_default_context(cafile=certifi.where())

        # Strip non-ASCII chars (e.g. non-breaking spaces in copy-pasted App Passwords)
        clean_password = "".join(c for c in cfg["password"] if ord(c) < 128).strip()

        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            server.ehlo()
            if cfg["use_tls"]:
                server.starttls(context=tls_ctx)
                server.ehlo()
            server.login(cfg["username"], clean_password)
            server.sendmail(cfg["sender"], [recipient], msg.as_string())

        log.info(f"[{PLUGIN_NAME}] ✅ Email sent successfully to {recipient}: {subject}")
        return {
            "status":    "success",
            "simulated": False,
            "message":   f"Email successfully sent to {recipient}.",
        }

    except smtplib.SMTPAuthenticationError:
        msg_text = (
            "SMTP authentication failed. "
            "For Gmail, ensure you are using a 16-character App Password "
            "(not your regular Gmail password) and that 2-Step Verification is enabled. "
            "Generate one at: https://myaccount.google.com/apppasswords"
        )
        log.error(f"[{PLUGIN_NAME}] {msg_text}")
        return {"status": "error", "message": msg_text}

    except smtplib.SMTPConnectError as exc:
        msg_text = (
            f"Could not connect to SMTP server {cfg['host']}:{cfg['port']}. "
            f"Check SMTP_HOST and SMTP_PORT. Error: {exc}"
        )
        log.error(f"[{PLUGIN_NAME}] {msg_text}")
        return {"status": "error", "message": msg_text}

    except smtplib.SMTPException as exc:
        log.exception(f"[{PLUGIN_NAME}] SMTP error: {exc}")
        return {"status": "error", "message": f"SMTP error: {exc}"}

    except Exception as exc:
        log.exception(f"[{PLUGIN_NAME}] Unexpected error sending email: {exc}")
        return {"status": "error", "message": f"Unexpected error: {exc}"}


# ═══════════════════════════════════════════════════════════════════════════
# Tool 1 — send_venue_booking_email
# ═══════════════════════════════════════════════════════════════════════════

async def send_venue_booking_email(
    venue_name: str,
    venue_address: str,
    venue_city: str,
    contact_email: str,
    guest_count: int,
    event_date: str,
    event_type: str,
    estimated_cost_usd: float,
    requester_name: Optional[str] = "Wedding Planning Guest",
    special_requests: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Send a venue booking request email to the venue contact.

    Args:
        venue_name:         Required. Name of the venue.
        venue_address:      Required. Full address of the venue.
        venue_city:         Required. City of the venue.
        contact_email:      Required. Venue contact email address.
        guest_count:        Required. Number of guests.
        event_date:         Required. Event date (YYYY-MM-DD).
        event_type:         Required. Type of event (e.g. ceremony_and_reception).
        estimated_cost_usd: Required. Estimated total cost in USD.
        requester_name:     Optional. Name of the person making the request.
        special_requests:   Optional. Any special requirements or notes.
        tool_context:       Injected by SAM runtime.
        tool_config:        Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:send_venue_booking_email]"
    log.info(f"{log_identifier} venue={venue_name!r} to={contact_email!r}")

    subject = f"REQUEST TO BOOK — {venue_name} — {event_date}"

    body = f"""Dear {venue_name} Events Team,

⚠️  THIS IS A REQUEST TO BOOK — NOT A CONFIRMED RESERVATION.

I am writing on behalf of {requester_name} to formally request to book your venue for an upcoming wedding. No booking is confirmed until you respond and both parties agree in writing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VENUE BOOKING REQUEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Venue Name      : {venue_name}
  Address         : {venue_address}
  City            : {venue_city}
  Event Date      : {event_date}
  Event Type      : {event_type.replace('_', ' ').title()}
  Guest Count     : {guest_count} guests
  Estimated Cost  : USD ${estimated_cost_usd:,.2f}
  Special Requests: {special_requests or 'None'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REQUESTER CONTACT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Name            : {requester_name}
  Phone           : {special_requests if special_requests else 'Please reply to this email'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please reply to confirm availability, share your contract and deposit requirements.

Warm regards,
Wedding Planning with SAM — Automated Booking System
"""

    result = _send_email(recipient=contact_email, subject=subject, body=body)

    if result["status"] != "success":
        return {"status": "error", "message": result["message"]}

    return {
        "status":         "success",
        "booking_type":   "venue",
        "email_sent_to":  contact_email,
        "venue_name":     venue_name,
        "event_date":     event_date,
        "guest_count":    guest_count,
        "simulated":      False,
        "message":        f"Venue booking request email sent to {contact_email} for {venue_name} on {event_date}.",
        "agent_response": (
            f"✅ A venue booking request has been sent on your behalf to "
            f"{venue_name}. Let's now proceed to confirm your caterer!"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 2 — send_caterer_booking_email
# ═══════════════════════════════════════════════════════════════════════════

async def send_caterer_booking_email(
    caterer_name: str,
    contact_email: str,
    guest_count: int,
    event_date: str,
    event_type: str,
    cuisine_choices: str,
    dietary_restrictions: Optional[str] = None,
    alcohol_service: Optional[bool] = None,
    dessert_option: Optional[str] = None,
    estimated_cost_usd: Optional[float] = None,
    requester_name: Optional[str] = "Wedding Planning Guest",
    special_requests: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Send a caterer booking request email to the caterer contact.

    Args:
        caterer_name:         Required. Name of the catering company.
        contact_email:        Required. Caterer contact email address.
        guest_count:          Required. Number of guests.
        event_date:           Required. Event date (YYYY-MM-DD).
        event_type:           Required. Type of event.
        cuisine_choices:      Required. Chosen cuisine style(s).
        dietary_restrictions: Optional. Dietary restrictions to accommodate.
        alcohol_service:      Optional. Whether alcohol service is required.
        dessert_option:       Optional. Dessert preference.
        estimated_cost_usd:   Optional. Estimated total cost in USD.
        requester_name:       Optional. Name of the person making the request.
        special_requests:     Optional. Any special requirements or notes.
        tool_context:         Injected by SAM runtime.
        tool_config:          Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:send_caterer_booking_email]"
    log.info(f"{log_identifier} caterer={caterer_name!r} to={contact_email!r}")

    subject = f"REQUEST TO BOOK — {caterer_name} — {event_date}"

    alcohol_str = "Yes" if alcohol_service else ("No" if alcohol_service is False else "To be confirmed")
    dessert_str = dessert_option.replace("_", " ").title() if dessert_option else "To be confirmed"
    diet_str    = dietary_restrictions or "None specified"
    cost_str    = f"USD ${estimated_cost_usd:,.2f}" if estimated_cost_usd else "To be quoted"

    body = f"""Dear {caterer_name} Team,

⚠️  THIS IS A REQUEST TO BOOK — NOT A CONFIRMED RESERVATION.

I am writing on behalf of {requester_name} to formally request a catering booking for an upcoming wedding. No booking is confirmed until you respond and both parties agree in writing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CATERING BOOKING REQUEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Caterer Name         : {caterer_name}
  Event Date           : {event_date}
  Event Type           : {event_type.replace('_', ' ').title()}
  Guest Count          : {guest_count} guests
  Cuisine Choice(s)    : {cuisine_choices}
  Dietary Requirements : {diet_str}
  Alcohol Service      : {alcohol_str}
  Dessert Option       : {dessert_str}
  Estimated Cost       : {cost_str}
  Special Requests     : {special_requests or 'None'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REQUESTER CONTACT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Name            : {requester_name}
  Phone           : {special_requests if special_requests else 'Please reply to this email'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please confirm your availability and provide details on tasting sessions, deposit and contract requirements.

Warm regards,
Wedding Planning with SAM — Automated Booking System
"""

    result = _send_email(recipient=contact_email, subject=subject, body=body)

    if result["status"] != "success":
        return {"status": "error", "message": result["message"]}

    return {
        "status":         "success",
        "booking_type":   "caterer",
        "email_sent_to":  contact_email,
        "caterer_name":   caterer_name,
        "event_date":     event_date,
        "guest_count":    guest_count,
        "simulated":      False,
        "message":        f"Caterer booking request email sent to {contact_email} for {caterer_name} on {event_date}.",
        "agent_response": (
            f"✅ A catering booking request has been sent on your behalf to "
            f"{caterer_name}. Let's now sort out your decorations!"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 3 — send_decorator_booking_email
# ═══════════════════════════════════════════════════════════════════════════

async def send_decorator_booking_email(
    decorator_name: str,
    contact_email: str,
    guest_count: int,
    event_date: str,
    venue_name: str,
    venue_setting: str,
    themes: Optional[str] = None,
    flower_preferences: Optional[str] = None,
    color_scheme: Optional[str] = None,
    estimated_cost_usd: Optional[float] = None,
    requester_name: Optional[str] = "Wedding Planning Guest",
    special_requests: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Send a decorator booking request email to the decorator contact.

    Args:
        decorator_name:     Required. Name of the decorator company.
        contact_email:      Required. Decorator contact email address.
        guest_count:        Required. Number of guests.
        event_date:         Required. Event date (YYYY-MM-DD).
        venue_name:         Required. Name of the wedding venue.
        venue_setting:      Required. 'indoor' or 'outdoor'.
        themes:             Optional. Chosen theme(s).
        flower_preferences: Optional. Flower preferences.
        color_scheme:       Optional. Preferred colour scheme.
        estimated_cost_usd: Optional. Estimated total cost in USD.
        requester_name:     Optional. Name of the person making the request.
        special_requests:   Optional. Any special requirements or notes.
        tool_context:       Injected by SAM runtime.
        tool_config:        Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:send_decorator_booking_email]"
    log.info(f"{log_identifier} decorator={decorator_name!r} to={contact_email!r}")

    subject = f"REQUEST TO BOOK — {decorator_name} — {event_date}"

    cost_str    = f"USD ${estimated_cost_usd:,.2f}" if estimated_cost_usd else "To be quoted"
    themes_str  = themes or "To be discussed"
    flowers_str = flower_preferences or "To be discussed"
    color_str   = color_scheme or "To be discussed"

    body = f"""Dear {decorator_name} Team,

⚠️  THIS IS A REQUEST TO BOOK — NOT A CONFIRMED RESERVATION.

I am writing on behalf of {requester_name} to request a wedding decoration booking and styling consultation. No booking is confirmed until you respond and both parties agree in writing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DECORATION BOOKING REQUEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Decorator Name      : {decorator_name}
  Event Date          : {event_date}
  Venue Name          : {venue_name}
  Venue Setting       : {venue_setting.title()}
  Guest Count         : {guest_count} guests
  Theme(s)            : {themes_str}
  Flower Preferences  : {flowers_str}
  Colour Scheme       : {color_str}
  Estimated Budget    : {cost_str}
  Special Requests    : {special_requests or 'None'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  REQUESTER CONTACT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Name            : {requester_name}
  Phone           : {special_requests if special_requests else 'Please reply to this email'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Please confirm availability, advise on styling consultation scheduling, site visits, and deposit requirements.

Warm regards,
Wedding Planning with SAM — Automated Booking System
"""

    result = _send_email(recipient=contact_email, subject=subject, body=body)

    if result["status"] != "success":
        return {"status": "error", "message": result["message"]}

    return {
        "status":          "success",
        "booking_type":    "decorator",
        "email_sent_to":   contact_email,
        "decorator_name":  decorator_name,
        "event_date":      event_date,
        "guest_count":     guest_count,
        "simulated":       False,
        "message":         f"Decorator booking request email sent to {contact_email} for {decorator_name} on {event_date}.",
        "agent_response": (
            f"✅ A decoration booking request has been sent on your behalf to "
            f"{decorator_name}. Your wedding is coming together beautifully! 🎉"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 4 — send_full_wedding_summary_email
# ═══════════════════════════════════════════════════════════════════════════

async def send_full_wedding_summary_email(
    requester_name: str,
    requester_email: str,
    event_date: str,
    guest_count: int,
    venue_name: str,
    venue_city: str,
    caterer_name: str,
    decorator_name: str,
    venue_cost_usd: Optional[float] = None,
    catering_cost_usd: Optional[float] = None,
    decoration_cost_usd: Optional[float] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Send a full wedding planning summary email to the couple.

    Args:
        requester_name:      Required. Name of the couple / requester.
        requester_email:     Required. Email address to send the summary to.
        event_date:          Required. Wedding date (YYYY-MM-DD).
        guest_count:         Required. Number of guests.
        venue_name:          Required. Name of the confirmed venue.
        venue_city:          Required. City of the venue.
        caterer_name:        Required. Name of the confirmed caterer.
        decorator_name:      Required. Name of the confirmed decorator.
        venue_cost_usd:      Optional. Estimated venue cost in USD.
        catering_cost_usd:   Optional. Estimated catering cost in USD.
        decoration_cost_usd: Optional. Estimated decoration cost in USD.
        tool_context:        Injected by SAM runtime.
        tool_config:         Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:send_full_wedding_summary_email]"
    log.info(f"{log_identifier} to={requester_email!r}")

    venue_str    = f"USD ${venue_cost_usd:,.2f}"      if venue_cost_usd    else "TBC"
    catering_str = f"USD ${catering_cost_usd:,.2f}"   if catering_cost_usd else "TBC"
    decor_str    = f"USD ${decoration_cost_usd:,.2f}" if decoration_cost_usd else "TBC"

    total     = (venue_cost_usd or 0) + (catering_cost_usd or 0) + (decoration_cost_usd or 0)
    total_str = f"USD ${total:,.2f}" if total > 0 else "TBC"

    subject = f"Your Wedding Booking Requests Summary — {event_date} 🎊"

    body = f"""Dear {requester_name},

Here is a summary of your wedding booking REQUESTS sent through Wedding Planning with SAM.

⚠️ IMPORTANT: These are booking REQUESTS only — not confirmed reservations.
Each vendor will contact you directly to confirm availability and next steps.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  YOUR WEDDING PLANNING SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Wedding Date    : {event_date}
  Location        : {venue_city}
  Guest Count     : {guest_count} guests

  ✉️  VENUE (Request Sent)
      {venue_name}
      Estimated Cost : {venue_str}

  ✉️  CATERING (Request Sent)
      {caterer_name}
      Estimated Cost : {catering_str}

  ✉️  DECORATION (Request Sent)
      {decorator_name}
      Estimated Cost : {decor_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ESTIMATED TOTAL INVESTMENT  : {total_str}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NEXT STEPS:
  • Each vendor has received a booking REQUEST email — not a confirmation.
  • Follow up with each vendor to confirm availability and sign contracts.
  • Arrange site visits, tastings, and styling consultations.
  • Confirm deposits only after receiving written confirmation from each vendor.

Wishing you a beautiful and memorable wedding day! 💍

With warmth,
Wedding Planning with SAM
"""

    result = _send_email(recipient=requester_email, subject=subject, body=body)

    if result["status"] != "success":
        return {"status": "error", "message": result["message"]}

    return {
        "status":          "success",
        "booking_type":    "summary",
        "email_sent_to":   requester_email,
        "event_date":      event_date,
        "total_estimated": total,
        "simulated":       False,
        "message":         f"Wedding planning summary email sent to {requester_email}.",
        "agent_response": (
            "🎊 A full wedding planning summary has been sent to your email address. "
            "Your venue, caterer, and decorator have all received booking requests. "
            "Congratulations and best wishes for your special day!"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 5 — save_email_log_report
# ═══════════════════════════════════════════════════════════════════════════

async def save_email_log_report(
    filename: str,
    emails_sent: str,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Save a log of all booking emails sent during this session as a text artifact.

    Args:
        filename:     Required. Desired output filename.
        emails_sent:  Required. Pipe-separated list of emails sent, each as
                      'type,recipient,vendor_name,event_date'.
        tool_context: Injected by SAM runtime.
        tool_config:  Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:save_email_log_report]"
    log.info(f"{log_identifier} filename='{filename}'")

    if not tool_context or not tool_context._invocation_context:
        return {"status": "error", "message": "ToolContext or InvocationContext is missing."}

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
        return {"status": "error", "message": f"Missing context parts: {', '.join(missing)}"}

    timestamp = datetime.now(timezone.utc)
    entries   = [e.strip() for e in emails_sent.split("|") if e.strip()]

    lines = [
        "=" * 70,
        "WEDDING BOOKING EMAIL LOG",
        f"Generated : {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 70, "",
    ]
    for i, entry in enumerate(entries, start=1):
        parts = [p.strip() for p in entry.split(",")]
        lines.append(f"[{i}] {' | '.join(parts)}")
    lines += ["", "=" * 70, "END OF LOG", "=" * 70]

    output_filename = filename.strip()
    if not output_filename.lower().endswith(".txt"):
        output_filename += ".txt"

    content_bytes = "\n".join(lines).encode("utf-8")
    metadata_dict = {
        "description":            f"Email log report generated by {PLUGIN_NAME}.",
        "source_tool":            "save_email_log_report",
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
            return {"status": "error", "message": f"Failed to save: {save_result.get('message')}"}

        return {
            "status": "success",
            "message": f"Email log saved as '{output_filename}'.",
            "output_filename": output_filename,
            "output_version": save_result["data_version"],
        }
    except Exception as exc:
        log.exception(f"{log_identifier} Unexpected error: {exc}")
        return {"status": "error", "message": f"Unexpected error: {exc}"}


# ═══════════════════════════════════════════════════════════════════════════
# Standalone test harness
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    async def run_tests():
        print("=" * 70)
        print("EMAIL AGENT — STANDALONE TESTS (REAL SMTP)")
        print("=" * 70)

        cfg = _get_smtp_config()
        print(f"\nSMTP Config:")
        print(f"  Host    : {cfg['host']}:{cfg['port']}")
        print(f"  Username: {cfg['username']}")
        print(f"  Sender  : {cfg['sender']}")
        print(f"  TLS     : {cfg['use_tls']}")

        err = _validate_smtp_config(cfg)
        if err:
            print(f"\n❌ Config error: {err}")
            print("Update SMTP_CONFIG at the top of this file before testing.")
            return

        class MockArtifactService:
            async def save_artifact(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}", "version": 1}
            async def save_artifact_metadata(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}.meta", "version": 1}

        class MockInvocationContext:
            def __init__(self):
                self.app_name         = "test_email_app"
                self.user_id          = "test_user"
                self.session_id       = "test_session_001"
                self.artifact_service = MockArtifactService()

        class MockToolContext:
            def __init__(self):
                self._invocation_context = MockInvocationContext()

        ctx = MockToolContext()

        print("\n--- Test 1: send_venue_booking_email ---")
        r1 = await send_venue_booking_email(
            venue_name="The Savoy Grand Ballroom",
            venue_address="Strand, London WC2R 0EZ",
            venue_city="London",
            contact_email="samdevuser@gmail.com",
            guest_count=200, event_date="2026-10-15",
            event_type="ceremony_and_reception",
            estimated_cost_usd=44000.00,
            requester_name="",
            tool_context=ctx,
        )
        print(f"Status: {r1['status']} | {r1['message']}")

        print("\n--- Test 2: send_caterer_booking_email ---")
        r2 = await send_caterer_booking_email(
            caterer_name="Spice Symphony",
            contact_email="samdevuser@gmail.com",
            guest_count=200, event_date="2026-10-15",
            event_type="ceremony_and_reception",
            cuisine_choices="Indian, Continental",
            dietary_restrictions="vegetarian, jain",
            alcohol_service=True, dessert_option="dessert_bar",
            estimated_cost_usd=15400.00,
            requester_name="", tool_context=ctx,
        )
        print(f"Status: {r2['status']} | {r2['message']}")

        print("\n--- Test 3: send_decorator_booking_email ---")
        r3 = await send_decorator_booking_email(
            decorator_name="The Floral Atelier London",
            contact_email="samdevuser@gmail.com",
            guest_count=200, event_date="2026-10-15",
            venue_name="The Savoy Grand Ballroom", venue_setting="indoor",
            themes="romantic, luxury", flower_preferences="roses, peonies",
            color_scheme="blush and ivory", estimated_cost_usd=9000.00,
            requester_name="", tool_context=ctx,
        )
        print(f"Status: {r3['status']} | {r3['message']}")

        print("\n--- Test 4: send_full_wedding_summary_email ---")
        r4 = await send_full_wedding_summary_email(
            requester_name="",
            requester_email="samdevuser@gmail.com",
            event_date="2026-10-15", guest_count=200,
            venue_name="The Savoy Grand Ballroom", venue_city="London",
            caterer_name="Spice Symphony",
            decorator_name="The Floral Atelier London",
            venue_cost_usd=44000.00, catering_cost_usd=15400.00,
            decoration_cost_usd=9000.00, tool_context=ctx,
        )
        print(f"Status: {r4['status']} | {r4['message']}")
        print(f"Agent response: {r4['agent_response']}")

        print("\n" + "=" * 70)
        print("All tests complete.")
        print("=" * 70)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    asyncio.run(run_tests())
