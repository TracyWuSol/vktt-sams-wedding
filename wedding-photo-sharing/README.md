# Wedding Photo Sharing

An event-photo distribution system: register guests with a selfie, upload group photos from the event, and every guest who appears in a photo gets it delivered automatically.

Face recognition runs on AWS Rekognition. The fan-out from "match found" to "email sent" goes through Solace PubSub+ as the event spine — the backend publishes an alert to a topic, an independent worker consumes it from a queue and sends the email.

## Architecture

```
┌──────────┐   /api/...    ┌──────────────┐  index/search   ┌──────────────┐
│ Frontend │ ────────────► │   Backend    │ ──────────────► │  AWS S3      │
│ (Vite,   │               │  (Express,   │                 │  + Rekognit. │
│  React)  │ ◄──results─── │   TS)        │ ◄──matches───── │              │
└──────────┘               └──────┬───────┘                 └──────────────┘
                                  │ publish
                                  ▼
                           ┌──────────────┐
                           │   Solace     │
                           │   PubSub+    │
                           │   broker     │
                           └──────┬───────┘
                                  │ queue: wedding/alerts/photos/email/>
                                  ▼
                           ┌──────────────┐   SMTP   ┌──────────────┐
                           │ Email Worker │ ───────► │ Recipient    │
                           │ (TS)         │          │ Inbox        │
                           └──────────────┘          └──────────────┘
```

Topics published by the backend per uploaded photo:

| Topic | Purpose |
|---|---|
| `wedding/s3/photos/uploaded` | New event photo arrived in S3 |
| `wedding/recognition/completed` | Rekognition finished matching |
| `wedding/alerts/{guestId}/{photoId}` | One alert per matched guest (all channels) |
| `wedding/alerts/photos/email/{guestId}/{photoId}` | Email-channel alerts (consumed by email-worker) |
| `wedding/notifications/send` | Notification-intent stream |

## Workspaces

This is an npm-workspaces monorepo with three TypeScript projects:

| Folder | Role | Doc |
|---|---|---|
| [`backend/`](./backend) | Express API: guest registry, photo upload, Rekognition orchestration, Solace publishing | [backend/README.md](./backend/README.md) |
| [`frontend/`](./frontend) | React + Vite admin and upload UI | [frontend/README.md](./frontend/README.md) |
| [`email-worker/`](./email-worker) | Standalone Solace queue consumer that sends email notifications | [email-worker/README.md](./email-worker/README.md) |

## Prerequisites

- Node.js 20+ and npm 10+
- An AWS account with permissions for S3 (read/write a bucket) and Rekognition (collection + face APIs)
- A Solace PubSub+ broker (Solace Cloud trial or self-hosted), with the email queue provisioned (see [Broker setup](#broker-setup))
- An SMTP account for sending email (Gmail App Password works)

## Quickstart

```bash
# 1. Install all workspace dependencies
npm install

# 2. Configure secrets
cp backend/.env.example backend/.env
# edit backend/.env with your AWS, Solace, SMTP values
# (the email-worker also reads backend/.env by default)

# 3. Provision the email queue on the broker (see "Broker setup" below)

# 4. Run all three workspaces concurrently
npm run dev
```

Then open <http://localhost:5173> — the Admin page registers guests, the Upload Photos page accepts event photos.

## Broker setup

The email-worker binds to a single queue and won't auto-create it. On first run, in the Solace admin UI (or via `semp` / config push):

1. Create queue `wedding_alerts_email_queue` (or whatever you set `EMAIL_SOLACE_QUEUE` to)
2. Add a topic subscription to that queue: `wedding/alerts/photos/email/>`
3. Set access type to *Exclusive* (only one worker reads at a time) and permissions allowing the Solace user from your `.env` to consume

Without the subscription the queue stays empty even though the backend is publishing. 

## Environment variables

All three workspaces share one `backend/.env` file in development. Full schema is in [`backend/.env.example`](./backend/.env.example).

| Variable | Used by | Notes |
|---|---|---|
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | backend | S3 + Rekognition |
| `AWS_SESSION_TOKEN`, `AWS_USE_SESSION_TOKEN` | backend | Required for STS/SSO temporary credentials |
| `AWS_S3_BUCKET` | backend | Photo storage bucket |
| `AWS_REKOGNITION_COLLECTION` | backend | Auto-created on startup |
| `SOLACE_HOST`, `SOLACE_VPN_NAME`, `SOLACE_USERNAME`, `SOLACE_PASSWORD` | backend, email-worker | Broker connection |
| `EMAIL_SOLACE_QUEUE` | email-worker | Queue to bind to |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USER`, `EMAIL_PASS`, `EMAIL_FROM` | email-worker | SMTP for outbound mail |
| `TWILIO_*` | backend | Optional, for SMS channel |

## Scripts

```bash
npm run dev      # all three workspaces with hot reload
npm run build    # tsc compile of every workspace
npm test         # backend Jest suite
```

## Tech stack

React 18, Vite, TypeScript 5, Express 4, AWS SDK v3 (S3, Rekognition), Solace `solclientjs` 10, nodemailer, Twilio, sharp, multer.

## License

Private / unpublished.
