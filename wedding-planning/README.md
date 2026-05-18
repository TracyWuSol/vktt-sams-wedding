# 💍 Wedding Planning with SAM

A multi-agent AI wedding planning system built on **Solace Agent Mesh (SAM)**. The system guides users through the entire wedding planning journey — finding a venue, booking catering, choosing decorations, and selecting photography — using a chain of specialised AI agents that automatically hand off between each other. All booking requests are sent via real SMTP email to vendors.

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ User Interfaces                                                 │
├─────────────────────────────────────────────────────────────────┤
│    WebUI                  │  External Events (S3 alerts)        │
│      ↓                    │           ↓                         │
│   WebUI Gateway           │   Event Mesh Gateway                │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ↓
                OrchestratorAgent
                            │
                    ┌───────┼───────┬──────────┐
                    ↓       ↓       ↓          ↓
         VenueAgent  CateringAgent  DecoratorAgent  PhotoAgent
                    │       │       │          │
                    └───────┼───────┴──────────┘
                            ↓
                    EmailAgent + LINE Tool
                            │
         ┌──────────────────┼──────────────────┐
         ↓                  ↓                  ↓
    SMTP Email          Dashboard          LINE Messages
                                           (to guests)
```

### Agent Chain (Automatic Handoffs)

| Step | Agent | Triggered By | What It Does |
|------|-------|-------------|-------------|
| 1 | **WeddingVenueAgent** | User | Searches 40 global venues across 8 cities; sends booking request email |
| 2 | **CateringAgent** | Venue confirmed | Searches 36 caterers; collects cuisine/dietary/alcohol/dessert preferences; sends booking request email |
| 3 | **DecoratorAgent** | Catering confirmed | Searches 36 decorators by city + indoor/outdoor; collects theme/flower/colour; sends booking request email |
| 4 | **PhotoAgent** | Decoration confirmed | Searches 40 photographers; presents 4 package tiers; sends booking request email |
| 5 | **EmailAgent** | Any booking | Centralised SMTP dispatcher for all vendor booking request emails |

> ⚠️ All emails are **booking REQUESTS** — not confirmations. Vendors contact the couple directly to confirm.

---

## 📁 Project Structure

```
vktt/
├── configs/                          ← SAM YAML configurations
│   ├── config.yaml                   ← Main SAM config (shared broker/model settings)
│   ├── shared_config.yaml            ← Shared anchors (broker, models, services)
│   ├── agents/
│   │   ├── main_orchestrator.yaml    ← Orchestrator agent (+ LINE tool)
│   │   ├── wedding-venue-agent.yaml  ← Venue agent
│   │   ├── catering-agent.yaml       ← Catering agent
│   │   ├── decorator-agent.yaml      ← Decorator agent
│   │   ├── photo-agent.yaml          ← Photography agent
│   │   └── email-agent.yaml          ← Email dispatch agent
│   └── gateways/
│       └── event_mesh_gateway.yaml   ← Event Mesh Gateway (S3 & LINE integration)
│
├── wedding-venue-agent/
│   └── src/wedding_venue_agent/
│       ├── __init__.py
│       ├── tools.py                  ← Venue search, booking, SMTP email
│       └── venues.csv                ← 40 venues (8 cities, local currency)
│
├── catering-agent/
│   └── src/catering_agent/
│       ├── __init__.py
│       ├── tools.py                  ← Caterer search, quote, SMTP email
│       └── caterers.csv              ← 36 caterers (8 cities, local currency)
│
├── decorator-agent/
│   └── src/decorator_agent/
│       ├── __init__.py
│       ├── tools.py                  ← Decorator search, quote, SMTP email
│       └── decorators.csv            ← 36 decorators (8 cities, local currency)
│
├── photo-agent/
│   └── src/photo_agent/
│       ├── __init__.py
│       ├── tools.py                  ← Photographer search, quote, SMTP email
│       └── photographers.csv         ← 40 photographers (8 cities, local currency)
│
├── email-agent/
│   └── src/email_agent/
│       ├── __init__.py
│       └── tools.py                  ← Centralised SMTP email tools
│
├── dashboard/
│   └── wedding_dashboard.html        ← Live wedding planning dashboard (served by WebUI gateway)
│
└── .env                              ← Environment variables (do not commit)
```

---

## 🌍 Coverage

### Cities
London 🇬🇧 · Tokyo 🇯🇵 · New York City 🇺🇸 · Paris 🇫🇷 · Mumbai 🇮🇳 · Seoul 🇰🇷 · Singapore 🇸🇬 · Sydney 🇦🇺

### Local Currencies
| City | Currency |
|------|---------|
| London | GBP (£) |
| Tokyo | JPY (¥) |
| New York City | USD ($) |
| Paris | EUR (€) |
| Mumbai | INR (₹) |
| Seoul | KRW (₩) |
| Singapore | SGD (S$) |
| Sydney | AUD (A$) |

---

## ⚙️ Prerequisites

- **Python 3.13+**
- **Solace Agent Mesh** installed in a virtual environment
- **A Gmail account** with an [App Password](https://myaccount.google.com/apppasswords) (for SMTP email)
- **certifi** Python package (`pip install certifi`)
- Either a **Solace Cloud** broker or run in **dev mode** (no broker needed)

---

## 🚀 Deployment Steps

### Step 1 — Clone / Set Up the Project

```bash
cd <sam-dir>
python3 -m venv .venv
source .venv/bin/activate
pip install solace-agent-mesh certifi
```

### Step 2 — Create the `.env` File

```bash
cat > .env << 'EOF'
# ── Broker (dev mode — no real broker needed) ──────────────────────────
SOLACE_DEV_MODE=true
USE_TEMPORARY_QUEUES=true

# ── Namespace ──────────────────────────────────────────────────────────
NAMESPACE=default_namespace

# ── LLM (update with your LiteLLM endpoint) ───────────────────────────
LLM_SERVICE_GENERAL_MODEL_NAME=your-model-name
LLM_SERVICE_ENDPOINT=https://your-litellm-endpoint
LLM_SERVICE_API_KEY=your-api-key

# ── WebUI ──────────────────────────────────────────────────────────────
FASTAPI_HOST=0.0.0.0
FASTAPI_PORT=3000
SESSION_SECRET_KEY=change-me-to-a-random-string
WEBUI_GATEWAY_ID=a2a_webui_app

# ── SMTP Email (Gmail) ─────────────────────────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-gmail@gmail.com
SMTP_PASSWORD=your-16-char-app-password
SMTP_FROM_ADDRESS=your-gmail@gmail.com

# ── LINE Messaging (optional — for guest notifications) ────────────────
LINE_API_ENDPOINT=https://api.line.biz/v2/bot/message/broadcast
LINE_CHANNEL_TOKEN=your-line-channel-token
LINE_BOT_USER_ID=your-bot-user-id

# ── Dashboard ──────────────────────────────────────────────────────────
WEDDING_DASHBOARD_URL=http://localhost:3000/wedding_dashboard.html
EOF
```

### Step 3 — Copy the Dashboard to SAM's Static Files

The dashboard must be served on the **same origin** (port 3000) as the SAM WebUI so that `localStorage` is shared between the chat and the dashboard.

```bash
# Find SAM's static files directory
STATIC_DIR=$(python3 -c "import solace_agent_mesh; import os; print(os.path.join(os.path.dirname(solace_agent_mesh.__file__), 'client/webui/frontend/static'))")

# Copy the dashboard
cp dashboard/wedding_dashboard.html "$STATIC_DIR/wedding_dashboard.html"

echo "Dashboard deployed to: $STATIC_DIR/wedding_dashboard.html"
echo "Access at: http://localhost:3000/wedding_dashboard.html"
```

### Step 4 — Verify File Structure

Run this check to confirm all CSV files and Python packages are in place:

```bash
cd <sam-dir>

echo "=== Checking agent packages ==="
for agent in wedding-venue-agent catering-agent decorator-agent photo-agent email-agent; do
  pkg=$(echo $agent | tr '-' '_')
  dir="$agent/src/$pkg"
  echo -n "$dir: "
  [ -f "$dir/__init__.py" ] && echo -n "__init__.py ✅ " || echo -n "__init__.py ❌ "
  [ -f "$dir/tools.py" ]    && echo -n "tools.py ✅ "    || echo -n "tools.py ❌ "
  echo ""
done

echo ""
echo "=== Checking CSV databases ==="
for f in \
  "wedding-venue-agent/src/wedding_venue_agent/venues.csv" \
  "catering-agent/src/catering_agent/caterers.csv" \
  "decorator-agent/src/decorator_agent/decorators.csv" \
  "photo-agent/src/photo_agent/photographers.csv"; do
  echo -n "$f: "
  [ -f "$f" ] && echo "✅ $(wc -l < $f) rows" || echo "❌ MISSING"
done

echo ""
echo "=== Checking YAML configs ==="
for f in \
  configs/agents/wedding-venue-agent.yaml \
  configs/agents/catering-agent.yaml \
  configs/agents/decorator-agent.yaml \
  configs/agents/photo-agent.yaml \
  configs/agents/email-agent.yaml \
  configs/agents/main_orchestrator.yaml \
  configs/gateways/event_mesh_gateway.yaml; do
  echo -n "$f: "
  [ -f "$f" ] && echo "✅" || echo "❌ MISSING"
done

echo ""
echo "=== Checking for {variable} errors in YAML instructions ==="
for f in configs/*.yaml; do
  count=$(grep -o '{[a-z_]*}' "$f" | grep -v '^\${' | wc -l | tr -d ' ')
  if [ "$count" -gt "0" ]; then
    echo "⚠️  $f has $count potential template variable(s):"
    grep -n '{[a-z_]*}' "$f" | grep -v '\${' | head -5
  fi
done
echo "Variable check complete."
```

### Step 5 — Start the WebUI + Orchestrator

```bash
cd <sam-dir>
source .venv/bin/activate
set -a; source .env; set +a

sam run configs/config.yaml
```

### Step 5b (Optional) — Start the Event Mesh Gateway

The Event Mesh Gateway bridges external Solace topics (S3 events, LINE notifications) into the SAM orchestrator. Use this if you want to enable **LINE notifications** and **S3 event processing**:

```bash
# In a separate terminal
cd <sam-dir>
source .venv/bin/activate
set -a; source .env; set +a

sam run configs/gateways/event_mesh_gateway.yaml
```

This starts the Event Mesh Gateway on port 9000 (configurable in the YAML). It will:
- Listen for S3 events on the `wedding/alerts/>` topic
- Forward them to the OrchestratorAgent
- Use the **LINE tool** (in the orchestrator) to send LINE notifications
- Publish responses on `event_mesh/responses/{correlation_id}` or `event_mesh/errors/{correlation_id}`

### Step 6 — Access the System

| URL | What it is |
|-----|-----------|
| `http://localhost:3000` | SAM WebUI — chat with the wedding planning agents |
| `http://localhost:3000/wedding_dashboard.html` | Live wedding planning dashboard |

---

## 💬 How to Use

### Starting a Wedding Planning Session

Type in the SAM WebUI chat:

> *"I need help planning my wedding"*

The **WeddingVenueAgent** will guide you through:

1. **Number of guests**
2. **City** (London, Tokyo, NYC, Paris, Mumbai, Seoul, Singapore, or Sydney)
3. **Event date** (must be in the future)
4. **Event type** (ceremony, reception, haldi, mehndi, sangeet, etc.)

### Booking Flow

```
1. Browse venues → Select one → Agent asks for your name & phone
2. Booking request email sent to venue → Dashboard updates ✉️
3. CateringAgent activates → Browse caterers → Confirm
4. Booking request email sent to caterer → Dashboard updates ✉️
5. DecoratorAgent activates → Choose theme/flowers/colours
6. Booking request email sent to decorator → Dashboard updates ✉️
7. PhotoAgent activates → Choose photography package
8. Booking request email sent to photographer → Dashboard updates ✉️
9. Full wedding summary shown 🎊
```

### Important Notes

- All emails are **booking REQUESTS** — vendors will contact you to confirm
- Bookings are **NOT confirmed** until the vendor replies and both parties agree in writing
- The dashboard auto-updates every 3 seconds from `localStorage`

---

## 📊 Dashboard

The dashboard at `http://localhost:3000/wedding_dashboard.html` shows:

- **Progress bar** — percentage of planning steps completed
- **Vendor cards** — Venue, Catering, Decoration, Photography with step indicators:
  - ✓ Chosen → ✉️ Request Sent → ✅ Confirmed
- **Activity timeline** — latest vendor interactions
- **Stats** — total tasks, vendors chosen, requests sent, confirmed

The dashboard **auto-updates** every 3 seconds via `localStorage` polling — no page refresh needed.

To **manually update** a vendor status, click the **+** button.

---

## 🔧 Configuration Reference

### SMTP Email

Edit `SMTP_CONFIG` in each `tools.py` or set environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `SMTP_USERNAME` | Your Gmail address | `you@gmail.com` |
| `SMTP_PASSWORD` | 16-char Gmail App Password | `abcd efgh ijkl mnop` |
| `SMTP_FROM_ADDRESS` | Sender display address | `you@gmail.com` |
| `SMTP_HOST` | SMTP server | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |

**Gmail App Password:** Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), enable 2-Step Verification, then generate a 16-character App Password.

### Vendor Contact Emails

All vendors in the CSV databases are configured with `samdevuser@gmail.com` as the contact email. To change this, edit the CSV files directly — the `contact_email` column controls where booking request emails are sent.

### Dashboard URL

Set `WEDDING_DASHBOARD_URL` in `.env`:
```bash
WEDDING_DASHBOARD_URL=http://localhost:3000/wedding_dashboard.html
```

This URL is embedded in every agent response as a persistent link.

### Event Mesh Gateway

The **Event Mesh Gateway** (`configs/gateways/event_mesh_gateway.yaml`) connects the SAM system to external event sources and enables LINE messaging. It:

- **Listens** for S3 events on the `wedding/alerts/>` Solace topic (published by the S3 Micro Integration Connector)
- **Transforms** inbound events into natural-language prompts
- **Delegates** to the OrchestratorAgent for processing
- **Uses** the **LINE tool** to send notifications to guests
- **Publishes** responses on `event_mesh/responses/{correlation_id}` (success) or `event_mesh/errors/{correlation_id}` (error)

**Configuration file**: [configs/gateways/event_mesh_gateway.yaml](configs/gateways/event_mesh_gateway.yaml)

**Inbound topics** (data plane):
- `wedding/alerts/>` — S3 events (e.g. `wedding/alerts/booking-update`, `wedding/alerts/s3-event`)

**Outbound topics** (data plane):
- `event_mesh/responses/{correlation_id}` — Success response (plain text)
- `event_mesh/errors/{correlation_id}` — Error response (JSON error object)

### LINE Tool

The **LINE tool** is embedded in the [main_orchestrator.yaml](configs/agents/main_orchestrator.yaml) config. It allows the OrchestratorAgent to send LINE messages to wedding guests:

```
Tool: send_line_notification
Input: recipient_id, message_text
Output: success status + LINE message ID
```

**Environment variables** for LINE:
```bash
LINE_API_ENDPOINT=https://api.line.biz/v2/...      # LINE Messaging API endpoint
LINE_CHANNEL_TOKEN=<your-line-channel-token>       # LINE channel access token
LINE_BOT_USER_ID=<your-bot-user-id>                # LINE bot user ID
```

The OrchestratorAgent can call this tool automatically when processing S3 events (e.g. "Wedding alert — send LINE notification about venue confirmation to guest 12345").

### Broker Mode

| Mode | Setting | Use Case |
|------|---------|---------|
| **Dev mode** (default) | `SOLACE_DEV_MODE=true` | Local development, no broker needed |
| **Solace Cloud** | `SOLACE_DEV_MODE=false` + cloud URL | Production |
| **Local Docker** | `SOLACE_DEV_MODE=false` + `localhost:8008` | Local production testing |

---

## 🗄️ CSV Database Schema

### venues.csv
`venue_id, name, city, country, venue_type, setting, address, capacity_min, capacity_max, base_price_local, price_per_guest_local, currency, supported_functions, amenities, description, contact_email, website, booked_dates`

### caterers.csv
`caterer_id, caterer_name, city, country, cuisines, min_guests, max_guests, base_price_per_head_local, alcohol_price_per_head_local, dessert_price_per_head_local, currency, alcohol_service, dessert_options, dietary_options, description, contact_email, website, packages`

### decorators.csv
`decorator_id, name, city, country, specializes_in, suitable_for, themes, flower_specialties, color_schemes, min_budget_local, max_budget_local, price_per_guest_local, currency, services_included, description, contact_email, website`

### photographers.csv
`photographer_id, name, city, country, specializes_in, style, packages, min_budget_local, max_budget_local, currency, contact_email, website, instagram, description`

---

## 🐛 Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `No module named 'wedding_venue_agent'` | Wrong `component_base_path` in YAML | Set `component_base_path: wedding-venue-agent/src` |
| `Module has no attribute 'search_venues'` | Wrong `tools.py` deployed to venue agent | Copy venue `tools.py` to `wedding-venue-agent/src/wedding_venue_agent/` |
| `No caterers/decorators found` | CSV column name mismatch (`_usd` vs `_local`) | Ensure `tools.py` uses `row.get("col_local", row.get("col_usd"))` |
| `Context variable not found: caterer_name` | `{variable}` syntax in YAML instruction | Remove all `{...}` from instruction blocks — use `[variable]` instead |
| `database is locked` | SQLite write contention | Enable `hybrid_buffer: true` in your WebUI gateway config; delete `*.db` files and restart |
| `SSL: CERTIFICATE_VERIFY_FAILED` | macOS Python SSL certs | Install certifi and use `ssl.create_default_context(cafile=certifi.where())` |
| `UnicodeEncodeError: ascii codec` | Non-breaking space in App Password | Strip with `"".join(c for c in pwd if ord(c) < 128).strip()` |
| Email goes to `sam@dev.local` | Tool not registered in YAML | Add the tool to the `tools:` list in the agent YAML |
| Dashboard not updating | Different `localStorage` origin | Serve dashboard from same port (3000) as SAM WebUI |

---

## 🔑 Key Design Decisions

1. **No `{variable}` in YAML instructions** — SAM resolves `{x}` as context variables at startup. Use `[x]` for examples.
2. **CSV-backed databases** — all vendor data in CSV files for easy editing without code changes.
3. **Local currency pricing** — each city uses its own currency (GBP, JPY, USD, EUR, INR, KRW, SGD, AUD).
4. **SMTP in each agent's tools.py** — each agent sends its own booking email directly from the vendor's `contact_email` in the CSV, avoiding incorrect hardcoded addresses.
5. **`request_venue_booking` tool** — venue bookings use a dedicated tool (not EmailAgent) to ensure the correct CSV email address is used.
6. **Dashboard on same origin** — `localStorage` requires same-origin access; the dashboard must be served from port 3000.
7. **`localStorage` polling** — dashboard polls every 3 seconds instead of relying on `postMessage` which doesn't work cross-tab.
8. **Event Mesh Gateway** — a second SAM gateway that bridges external Solace topics (S3 events, alerts) into the SAM control plane, enabling integration with external event sources without modifying agent code.
9. **LINE tool in OrchestratorAgent** — the orchestrator can send LINE messages to guests directly via the LINE Messaging API, triggered by S3 events or user requests.

---

## 📦 Dependencies

```bash
pip install \
  solace-agent-mesh \
  certifi \
  google-adk \
  litellm
```

---

## 🤝 Support

This project is managed by **Wedding Planning with SAM** via Solace Agent Mesh.
For issues, check the `sam.log` file and the troubleshooting table above.

---

*Made with 💛 by Wedding Planning with SAM*
