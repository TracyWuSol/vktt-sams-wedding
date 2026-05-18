"""
Wedding Decorator Agent Tools
A specialized agent for finding wedding decorators based on city, venue setting
(indoor/outdoor), theme, colour scheme, flower preferences, and budget.
Triggered automatically after the Catering Agent confirms a booking.
"""

import csv
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.adk.tools import ToolContext
from solace_agent_mesh.agent.utils.artifact_helpers import (
    save_artifact_with_metadata,
    DEFAULT_SCHEMA_MAX_KEYS,
)
from solace_agent_mesh.agent.utils.context_helpers import get_original_session_id

log = logging.getLogger(__name__)

PLUGIN_NAME = "decorator_agent"

# ---------------------------------------------------------------------------
# CSV path — place decorators.csv alongside this file:
#   decorator-agent/src/decorator_agent/decorators.csv
# ---------------------------------------------------------------------------

_CSV_PATH = Path(__file__).parent / "decorators.csv"

# ---------------------------------------------------------------------------
# Dashboard integration
# ---------------------------------------------------------------------------

import os as _os

WEDDING_DASHBOARD_URL: str = _os.environ.get(
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
# Valid option sets
# ---------------------------------------------------------------------------

VALID_SETTINGS = {"indoor", "outdoor", "both"}

VALID_THEMES = {
    "romantic", "classic", "garden", "bohemian", "royal", "luxury",
    "black_tie", "contemporary", "art_deco", "japanese_minimalist",
    "cherry_blossom", "zen", "gatsby", "industrial_chic", "rustic",
    "parisian_romance", "french_classic", "vintage", "indian_royal",
    "mughal", "traditional", "bollywood", "beach", "tropical",
    "korean_romantic", "minimal_chic", "botanical", "coastal",
    "english_garden", "woodland", "enchanted_forest", "whimsical",
    "farmhouse", "provencal", "multicultural", "fusion", "shinto",
    "peranakan", "heritage", "urban_rooftop", "skyline",
}

VALID_CITIES = {
    "london", "tokyo", "new york city", "paris",
    "mumbai", "seoul", "singapore", "sydney",
}


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------

def _load_decorators_from_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Load and parse decorators from CSV into a list of dicts."""
    if not csv_path.exists():
        log.error(f"[{PLUGIN_NAME}] decorators.csv not found at {csv_path}")
        return []

    decorators: List[Dict[str, Any]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dec = {
                    "id":               row["decorator_id"].strip(),
                    "name":             row["name"].strip(),
                    "city":             row["city"].strip(),
                    "country":          row["country"].strip(),
                    "specializes_in":   [
                        s.strip() for s in row["specializes_in"].split(",")
                    ],
                    "suitable_for":     [
                        s.strip() for s in row["suitable_for"].split(",")
                    ],
                    "themes":           [
                        t.strip().lower().replace(" ", "_")
                        for t in row["themes"].split(",")
                    ],
                    "flower_specialties": [
                        f.strip() for f in row["flower_specialties"].split(",")
                    ],
                    "color_schemes":    [
                        c.strip() for c in row["color_schemes"].split(",")
                    ],
                    # Support both local-currency columns (decorators_local.csv)
                    # and original USD columns (decorators.csv)
                    "min_budget_usd":      float(row.get("min_budget_local",      row.get("min_budget_usd",      0))),
                    "max_budget_usd":      float(row.get("max_budget_local",      row.get("max_budget_usd",      0))),
                    "price_per_guest_usd": float(row.get("price_per_guest_local", row.get("price_per_guest_usd", 0))),
                    "currency":            row.get("currency", "USD").strip(),
                    "services_included": [
                        s.strip() for s in row["services_included"].split(",")
                    ],
                    "description":      row["description"].strip(),
                    "contact_email":    row["contact_email"].strip(),
                    "website":          row["website"].strip(),
                }
                decorators.append(dec)
            except (KeyError, ValueError) as exc:
                log.warning(
                    f"[{PLUGIN_NAME}] Skipping malformed CSV row: {exc} — {row}"
                )

    log.info(f"[{PLUGIN_NAME}] Loaded {len(decorators)} decorators from {csv_path}")
    return decorators


# Module-level database — loaded once on import
_DECORATOR_DB: List[Dict[str, Any]] = _load_decorators_from_csv(_CSV_PATH)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_decorator_summary(dec: Dict[str, Any]) -> Dict[str, Any]:
    """Return a clean serialisable decorator summary."""
    return {
        "decorator_id":       dec["id"],
        "name":               dec["name"],
        "city":               dec["city"],
        "country":            dec["country"],
        "specializes_in":     dec["specializes_in"],
        "suitable_for":       dec["suitable_for"],
        "themes":             dec["themes"],
        "flower_specialties": dec["flower_specialties"],
        "color_schemes":      dec["color_schemes"],
        "min_budget_usd":     dec["min_budget_usd"],
        "max_budget_usd":     dec["max_budget_usd"],
        "price_per_guest_usd": dec["price_per_guest_usd"],
        "currency":            dec.get("currency", "USD"),
        "services_included":  dec["services_included"],
        "description":        dec["description"],
        "contact_email":      dec["contact_email"],
        "website":            dec["website"],
    }


def _score_decorator(
    dec: Dict[str, Any],
    themes: List[str],
    flowers: List[str],
    color_scheme: Optional[str],
) -> int:
    """
    Score a decorator by how well it matches the user's preferences.
    Higher = better match. Used for relevance-sorting.
    """
    score = 0
    dec_themes  = set(dec["themes"])
    dec_flowers = {f.lower() for f in dec["flower_specialties"]}
    dec_colors  = " ".join(dec["color_schemes"]).lower()

    for theme in themes:
        if theme.lower().replace(" ", "_") in dec_themes:
            score += 3
    for flower in flowers:
        if flower.lower() in dec_flowers:
            score += 2
    if color_scheme and color_scheme.lower() in dec_colors:
        score += 2
    return score


# ---------------------------------------------------------------------------
# Tool 1 — get_decoration_options
# ---------------------------------------------------------------------------

async def get_decoration_options(
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Return all available theme categories, popular flower types, colour scheme
    families, and setting options to present to the user before searching.
    Always call this tool first to guide the user through their preferences.
    """
    log_identifier = f"[{PLUGIN_NAME}:get_decoration_options]"
    log.info(f"{log_identifier} Returning decoration preference options.")

    return {
        "status":  "success",
        "message": "Here are the decoration preferences to present to the user.",
        "settings": [
            {"id": "indoor",  "description": "Ballrooms, halls, hotel venues — controlled environment, unlimited styling options."},
            {"id": "outdoor", "description": "Gardens, beaches, terraces, rooftops — natural backdrops, weather-dependent."},
        ],
        "themes": [
            {"id": "romantic",            "description": "Soft florals, candles, dreamy draping — timeless and intimate."},
            {"id": "classic",             "description": "Traditional elegance — symmetry, white florals, formal arrangements."},
            {"id": "luxury_black_tie",    "description": "Chandeliers, gold accents, opulent tablescapes, crystal."},
            {"id": "bohemian",            "description": "Pampas grass, macrame, dried flowers, relaxed and free-spirited."},
            {"id": "garden",              "description": "Lush greenery, wildflowers, naturalistic arrangements."},
            {"id": "art_deco_gatsby",     "description": "Gold geometric patterns, feathers, 1920s glamour."},
            {"id": "rustic_farmhouse",    "description": "Wood, mason jars, sunflowers, barn chic."},
            {"id": "tropical_beach",      "description": "Bird of paradise, frangipani, tiki torches, coastal."},
            {"id": "indian_royal",        "description": "Marigolds, jasmine, mandap, vibrant colours, traditional."},
            {"id": "japanese_minimalist", "description": "Ikebana, cherry blossom, zen simplicity, clean lines."},
            {"id": "parisian_romance",    "description": "Roses, peonies, French elegance, antique props."},
            {"id": "enchanted_forest",    "description": "Ferns, fairy lights, moss, woodland magic."},
            {"id": "korean_modern",       "description": "Sleek contemporary design, neon, glass, monochromes."},
            {"id": "multicultural",       "description": "Fusion of traditions — best for intercultural ceremonies."},
            {"id": "coastal_nautical",    "description": "Driftwood, sea flowers, rope, maritime freshness."},
            {"id": "provencal_rustic",    "description": "Lavender, sunflowers, linen, French countryside warmth."},
        ],
        "popular_flowers": [
            "Roses", "Peonies", "Marigolds", "Orchids", "Cherry Blossom",
            "Lavender", "Sunflowers", "Jasmine", "Hydrangeas", "Lotus",
            "Wildflowers", "Pampas Grass", "Frangipani", "Ranunculus",
            "Native Australian Flowers (Waratahs, Banksias, Proteas)",
            "Dried/Preserved Flowers", "Tropical Heliconias", "Lilies",
            "Calla Lilies", "Tulips",
        ],
        "colour_scheme_families": [
            {"id": "white_and_gold",      "description": "Timeless luxury — suits any venue type."},
            {"id": "blush_and_ivory",     "description": "Soft romantic — indoor and garden venues."},
            {"id": "jewel_tones",         "description": "Emerald, sapphire, ruby — rich and dramatic indoors."},
            {"id": "pastel_rainbow",      "description": "Dreamy soft tones — garden and outdoor."},
            {"id": "black_and_gold",      "description": "Bold glamour — indoor luxury venues."},
            {"id": "terracotta_and_rust", "description": "Earthy warmth — outdoor and rustic."},
            {"id": "tropical_colours",    "description": "Vibrant fuchsia, turquoise, coral — beach and outdoor."},
            {"id": "vibrant_indian",      "description": "Saffron, fuchsia, royal blue — Indian ceremonies."},
            {"id": "monochrome",          "description": "All-white or all-black — modern and striking."},
            {"id": "coastal_blues",       "description": "Ocean blue, navy, seafoam — coastal venues."},
        ],
        "budget_guidance": (
            "Decorator budgets range from USD $800 (intimate setups) to $80,000+ (opulent installations). "
            "Please ask the user for their total decoration budget."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 2 — search_decorators
# ---------------------------------------------------------------------------

async def search_decorators(
    city: str,
    setting: str,
    guest_count: int,
    budget_usd: Optional[float] = None,
    themes: Optional[str] = None,
    flower_preferences: Optional[str] = None,
    color_scheme: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Search for wedding decorators matching city, venue setting, budget,
    themes, flower preferences, and colour scheme.

    Args:
        city:               Required. City of the wedding venue (e.g. 'London', 'Tokyo').
        setting:            Required. 'indoor', 'outdoor', or 'both'.
        guest_count:        Required. Number of guests — used to estimate total decoration cost.
        budget_usd:         Optional. Maximum total decoration budget in USD.
        themes:             Optional. Comma-separated theme preferences
                            (e.g. 'romantic,garden' or 'indian_royal').
        flower_preferences: Optional. Comma-separated flower preferences
                            (e.g. 'roses,peonies').
        color_scheme:       Optional. Preferred colour scheme keyword
                            (e.g. 'blush and ivory' or 'white and gold').
        tool_context:       Injected by SAM runtime.
        tool_config:        Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:search_decorators]"
    log.info(
        f"{log_identifier} city={city!r} setting={setting!r} "
        f"guest_count={guest_count} budget={budget_usd} "
        f"themes={themes!r} flowers={flower_preferences!r} color={color_scheme!r}"
    )

    # ── Validation ──────────────────────────────────────────────────────────
    if not city or not city.strip():
        return {"status": "error", "message": "city must not be empty."}

    if setting.lower() not in VALID_SETTINGS:
        return {
            "status":  "error",
            "message": (
                f"Invalid setting '{setting}'. Valid values: indoor, outdoor, both."
            ),
        }

    if not isinstance(guest_count, int) or guest_count <= 0:
        return {
            "status":  "error",
            "message": f"guest_count must be a positive integer, got {guest_count!r}.",
        }

    # ── Parse optional filters ──────────────────────────────────────────────
    requested_themes: List[str] = []
    if themes:
        requested_themes = [
            t.strip().lower().replace(" ", "_")
            for t in themes.split(",") if t.strip()
        ]

    requested_flowers: List[str] = []
    if flower_preferences:
        requested_flowers = [
            f.strip().lower() for f in flower_preferences.split(",") if f.strip()
        ]

    # ── Filter decorators ───────────────────────────────────────────────────
    results: List[Dict[str, Any]] = []

    for dec in _DECORATOR_DB:

        # City filter (case-insensitive)
        if city.strip().lower() not in dec["city"].lower():
            continue

        # Setting filter
        if setting.lower() == "both":
            # Accept any decorator that handles at least one setting
            pass
        else:
            if setting.lower() not in dec["suitable_for"]:
                continue

        # Budget filter (total = price_per_guest * guest_count, must not exceed budget)
        estimated_total = dec["price_per_guest_usd"] * guest_count
        if budget_usd is not None:
            if estimated_total > budget_usd:
                # Also check if minimum package is affordable
                if dec["min_budget_usd"] > budget_usd:
                    continue

        summary = _safe_decorator_summary(dec)
        summary["estimated_total_usd"] = round(
            dec["price_per_guest_usd"] * guest_count, 2
        )
        summary["match_score"] = _score_decorator(
            dec, requested_themes, requested_flowers, color_scheme
        )
        results.append(summary)

    # Sort: match_score desc, then estimated_total asc
    results.sort(key=lambda d: (-d["match_score"], d["estimated_total_usd"]))

    log.info(f"{log_identifier} Found {len(results)} matching decorator(s).")
    return {
        "status":        "success",
        "message":       f"Found {len(results)} decorator(s) in {city} matching your preferences.",
        "total_results": len(results),
        "decorators":    results,
        "search_criteria": {
            "city":             city,
            "setting":          setting,
            "guest_count":      guest_count,
            "budget_usd":       budget_usd,
            "themes":           requested_themes or None,
            "flower_preferences": requested_flowers or None,
            "color_scheme":     color_scheme,
        },
    }


# ---------------------------------------------------------------------------
# Tool 3 — get_decorator_details
# ---------------------------------------------------------------------------

async def get_decorator_details(
    decorator_id: str,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Retrieve full details for a specific decorator by ID (e.g. 'D001').

    Args:
        decorator_id: Required. The decorator identifier.
        tool_context: Injected by SAM runtime.
        tool_config:  Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:get_decorator_details]"
    log.info(f"{log_identifier} decorator_id={decorator_id!r}")

    if not decorator_id or not decorator_id.strip():
        return {"status": "error", "message": "decorator_id must not be empty."}

    decorator_id = decorator_id.strip().upper()

    for dec in _DECORATOR_DB:
        if dec["id"] == decorator_id:
            log.info(f"{log_identifier} Found: {dec['name']}")
            return {
                "status":    "success",
                "message":   f"Decorator '{dec['name']}' retrieved successfully.",
                "decorator": _safe_decorator_summary(dec),
            }

    log.warning(f"{log_identifier} Decorator not found: {decorator_id!r}")
    return {
        "status":  "error",
        "message": (
            f"No decorator found with ID '{decorator_id}'. "
            f"Valid IDs: {[d['id'] for d in _DECORATOR_DB]}"
        ),
    }


# ---------------------------------------------------------------------------
# Tool 4 — get_decoration_quote
# ---------------------------------------------------------------------------

async def get_decoration_quote(
    decorator_id: str,
    guest_count: int,
    themes: Optional[str] = None,
    flower_preferences: Optional[str] = None,
    color_scheme: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate a detailed decoration quote for a specific decorator.

    Args:
        decorator_id:       Required. Decorator identifier (e.g. 'D004').
        guest_count:        Required. Number of guests.
        themes:             Optional. Comma-separated theme selections.
        flower_preferences: Optional. Comma-separated flower preferences.
        color_scheme:       Optional. Preferred colour scheme.
        tool_context:       Injected by SAM runtime.
        tool_config:        Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:get_decoration_quote]"
    log.info(
        f"{log_identifier} decorator_id={decorator_id!r} guest_count={guest_count}"
    )

    if not decorator_id or not decorator_id.strip():
        return {"status": "error", "message": "decorator_id must not be empty."}

    if not isinstance(guest_count, int) or guest_count <= 0:
        return {
            "status":  "error",
            "message": f"guest_count must be a positive integer, got {guest_count!r}.",
        }

    decorator_id = decorator_id.strip().upper()

    for dec in _DECORATOR_DB:
        if dec["id"] != decorator_id:
            continue

        estimated_total = round(dec["price_per_guest_usd"] * guest_count, 2)

        # Build matched preferences summary
        requested_themes  = [
            t.strip() for t in themes.split(",") if t.strip()
        ] if themes else []
        requested_flowers = [
            f.strip() for f in flower_preferences.split(",") if f.strip()
        ] if flower_preferences else []

        matched_themes  = [
            t for t in requested_themes
            if t.lower().replace(" ", "_") in dec["themes"]
        ]
        matched_flowers = [
            f for f in requested_flowers
            if f.lower() in {x.lower() for x in dec["flower_specialties"]}
        ]

        log.info(
            f"{log_identifier} Quote: {dec['name']} = ${estimated_total:,.2f}"
        )
        return {
            "status":  "success",
            "message": (
                f"Quote for '{dec['name']}' — estimated total "
                f"${estimated_total:,.2f} for {guest_count} guests."
            ),
            "quote": {
                "decorator_id":       dec["id"],
                "decorator_name":     dec["name"],
                "city":               dec["city"],
                "country":            dec["country"],
                "suitable_for":       dec["suitable_for"],
                "guest_count":        guest_count,
                "price_per_guest":    dec["price_per_guest_usd"],
                "estimated_total":    estimated_total,
                "min_package":        dec["min_budget_usd"],
                "max_package":        dec["max_budget_usd"],
                "themes_available":   dec["themes"],
                "matched_themes":     matched_themes or "All themes available",
                "flowers_available":  dec["flower_specialties"],
                "matched_flowers":    matched_flowers or "Discuss with decorator",
                "color_schemes":      dec["color_schemes"],
                "requested_color":    color_scheme or "Flexible",
                "services_included":  dec["services_included"],
                "contact_email":      dec["contact_email"],
                "website":            dec["website"],
                "next_steps": (
                    "Contact the decorator to arrange a styling consultation, "
                    "review mood boards, and confirm your package."
                ),
            },
        }

    log.warning(f"{log_identifier} Decorator not found: {decorator_id!r}")
    return {
        "status":  "error",
        "message": f"No decorator found with ID '{decorator_id}'.",
    }


# ---------------------------------------------------------------------------
# Tool 5 — save_decoration_quote_report
# ---------------------------------------------------------------------------

async def save_decoration_quote_report(
    filename: str,
    decorator_id: str,
    guest_count: int,
    themes: Optional[str] = None,
    flower_preferences: Optional[str] = None,
    color_scheme: Optional[str] = None,
    requester_name: str = "Wedding Planning Guest",
    requester_phone: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
    tool_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate a decoration quote and save it as a text report artifact.
    This triggers a booking REQUEST — not a confirmed reservation.

    Args:
        filename:           Required. Desired output filename.
        decorator_id:       Required. Decorator identifier.
        guest_count:        Required. Number of guests.
        themes:             Optional. Comma-separated theme selections.
        flower_preferences: Optional. Comma-separated flower preferences.
        color_scheme:       Optional. Preferred colour scheme.
        requester_name:     Required. Full name collected from user before calling.
        requester_phone:    Required. Phone number collected from user before calling.
        tool_context:       Injected by SAM runtime.
        tool_config:        Optional runtime config dict.
    """
    log_identifier = f"[{PLUGIN_NAME}:save_decoration_quote_report]"
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

    # ── Generate quote ──────────────────────────────────────────────────────
    quote_result = await get_decoration_quote(
        decorator_id=decorator_id,
        guest_count=guest_count,
        themes=themes,
        flower_preferences=flower_preferences,
        color_scheme=color_scheme,
        tool_context=tool_context,
        tool_config=tool_config,
    )

    if quote_result.get("status") == "error":
        return quote_result

    q = quote_result["quote"]
    timestamp = datetime.now(timezone.utc)

    # ── Build report text ───────────────────────────────────────────────────
    themes_str  = themes or "No specific theme"
    flowers_str = flower_preferences or "No specific preference"
    lines = [
        "=" * 70,
        "WEDDING DECORATION QUOTE REPORT",
        f"Generated : {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 70,
        "",
        "DECORATOR DETAILS",
        "-" * 40,
        f"  Decorator         : {q['decorator_name']} ({q['decorator_id']})",
        f"  City              : {q['city']}, {q['country']}",
        f"  Suitable For      : {', '.join(q['suitable_for'])}",
        f"  Contact Email     : {q['contact_email']}",
        f"  Website           : {q['website']}",
        "",
        "EVENT PREFERENCES",
        "-" * 40,
        f"  Guest Count       : {q['guest_count']}",
        f"  Themes            : {themes_str}",
        f"  Flower Preference : {flowers_str}",
        f"  Colour Scheme     : {q['requested_color']}",
        f"  Matched Themes    : {q['matched_themes'] if isinstance(q['matched_themes'], str) else ', '.join(q['matched_themes'])}",
        f"  Matched Flowers   : {q['matched_flowers'] if isinstance(q['matched_flowers'], str) else ', '.join(q['matched_flowers'])}",
        "",
        "PRICING",
        "-" * 40,
        f"  Price Per Guest   : ${q['price_per_guest']:,.2f}",
        f"  Estimated Total   : ${q['estimated_total']:,.2f}",
        f"  Min Package       : ${q['min_package']:,.2f}",
        f"  Max Package       : ${q['max_package']:,.2f}",
        "",
        "SERVICES INCLUDED",
        "-" * 40,
        f"  {', '.join(q['services_included'])}",
        "",
        "COLOUR SCHEMES OFFERED",
        "-" * 40,
        f"  {', '.join(q['color_schemes'])}",
        "",
        "NEXT STEPS",
        "-" * 40,
        f"  {q['next_steps']}",
        "",
        "=" * 70,
        "END OF REPORT",
        "=" * 70,
    ]

    report_text    = "\n".join(lines)
    output_filename = filename.strip()
    if not output_filename.lower().endswith(".txt"):
        output_filename += ".txt"

    content_bytes = report_text.encode("utf-8")
    metadata_dict = {
        "description":            f"Wedding decoration quote report generated by {PLUGIN_NAME}.",
        "source_tool":            "save_decoration_quote_report",
        "decorator_id":           decorator_id,
        "guest_count":            guest_count,
        "estimated_total":        q["estimated_total"],
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
            f"{log_identifier} Report '{output_filename}' "
            f"v{save_result['data_version']} saved."
        )
        return {
            "status":          "success",
            "message": (
                f"Decoration quote report '{output_filename}' saved as artifact "
                f"v{save_result['data_version']}. "
                f"Estimated total: ${q['estimated_total']:,.2f}."
            ),
            "output_filename":  output_filename,
            "output_version":   save_result["data_version"],
            "estimated_total":  q["estimated_total"],
            "requester_name":   requester_name,
            "requester_phone":  requester_phone,
            "agent_response": (
                f"✅ A **request to book** {q['decorator_name']} has been sent on your behalf.\n\n"
                f"⚠️ This is a **booking request only** — not a confirmed reservation. "
                f"The decorator will contact you to confirm availability and details.\n\n"
                f"Let's now choose your photographer!"
                + _dashboard_link("Decoration booking request sent — dashboard updated!")
            ),
            "dashboard_update": _dashboard_update_script(
                task_id="decoration",
                vendor=q["decorator_name"],
                city=q["city"],
                chosen=True,
                emailed=True,
                booked=False,
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
        print("DECORATOR AGENT — STANDALONE TESTS")
        print("=" * 70)

        class MockArtifactService:
            async def save_artifact(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}", "version": 1}
            async def save_artifact_metadata(self, **kwargs):
                return {"uri": f"mock://{kwargs.get('filename')}.meta", "version": 1}

        class MockInvocationContext:
            def __init__(self):
                self.app_name         = "test_decorator_app"
                self.user_id          = "test_user"
                self.session_id       = "test_session_001"
                self.artifact_service = MockArtifactService()

        class MockToolContext:
            def __init__(self):
                self._invocation_context = MockInvocationContext()

        ctx = MockToolContext()
        print(f"\nCSV path: {_CSV_PATH}")
        print(f"Decorators loaded: {len(_DECORATOR_DB)}")

        # Test 1: get_decoration_options
        print("\n--- Test 1: get_decoration_options ---")
        r1 = await get_decoration_options(tool_context=ctx)
        print(f"Status: {r1['status']}")
        print(f"Themes available: {len(r1['themes'])}")
        print(f"Flowers available: {len(r1['popular_flowers'])}")

        # Test 2: search London indoor romantic
        print("\n--- Test 2: search London indoor romantic (200 guests, $20k) ---")
        r2 = await search_decorators(
            city="London", setting="indoor", guest_count=200,
            budget_usd=20000, themes="romantic,luxury",
            flower_preferences="roses,peonies",
            color_scheme="blush and ivory",
            tool_context=ctx,
        )
        print(f"Status: {r2['status']} | Found: {r2.get('total_results', 0)}")
        for d in r2.get("decorators", []):
            print(
                f"  • {d['name']} [{d['decorator_id']}] "
                f"score={d['match_score']} est=${d['estimated_total_usd']:,.0f}"
            )

        # Test 3: search Mumbai outdoor Indian
        print("\n--- Test 3: search Mumbai outdoor Indian royal (300 guests) ---")
        r3 = await search_decorators(
            city="Mumbai", setting="outdoor", guest_count=300,
            themes="indian_royal,traditional",
            flower_preferences="marigolds,jasmine",
            color_scheme="red and gold",
            tool_context=ctx,
        )
        print(f"Status: {r3['status']} | Found: {r3.get('total_results', 0)}")
        for d in r3.get("decorators", []):
            print(f"  • {d['name']} — {', '.join(d['themes'][:3])}")

        # Test 4: get_decoration_quote
        print("\n--- Test 4: get_decoration_quote (D001, 200 guests) ---")
        r4 = await get_decoration_quote(
            decorator_id="D001",
            guest_count=200,
            themes="romantic,garden",
            flower_preferences="roses,peonies",
            color_scheme="blush and ivory",
            tool_context=ctx,
        )
        print(f"Status: {r4['status']}")
        if r4["status"] == "success":
            q = r4["quote"]
            print(f"Decorator     : {q['decorator_name']}")
            print(f"Est Total     : ${q['estimated_total']:,.2f}")
            print(f"Matched Themes: {q['matched_themes']}")

        # Test 5: save report
        print("\n--- Test 5: save_decoration_quote_report ---")
        r5 = await save_decoration_quote_report(
            filename="london_decor_quote",
            decorator_id="D001",
            guest_count=200,
            themes="romantic,garden",
            flower_preferences="roses,peonies",
            color_scheme="blush and ivory",
            tool_context=ctx,
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