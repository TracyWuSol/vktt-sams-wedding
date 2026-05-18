---
marp: true
theme: default
paginate: true
size: 16:9
header: 'Wedding Photo Sharing — Architecture'
---

# Wedding Photo Sharing
### Face-recognition powered photo delivery, in real time

Built on React • Express • AWS • Solace PubSub+

---

## The Problem

Wedding guests take hundreds of photos — but **nobody knows which photos contain whom**.

Manual sorting is slow. Group chats get noisy. Guests leave without their own pictures.

**Goal:** every guest automatically receives the photos they appear in, within seconds of upload.

---

## High-Level Architecture

```
┌──────────┐   upload    ┌─────────────┐   index    ┌──────────────┐
│ Frontend │ ──────────► │   Express   │ ─────────► │ S3 / Rekog.  │
│  (React) │             │  Backend    │            │   AWS        │
└──────────┘             └──────┬──────┘            └──────┬───────┘
                                │ recognize                │
                                │ match guests             │
                                ▼                          ▼
                         ┌─────────────┐            ┌──────────────┐
                         │   Solace    │            │     S3       │
                         │   PubSub+   │◄───────────│ notification/│
                         │   topics    │            │   folder     │
                         └──────┬──────┘            └──────────────┘
                                │ wedding/alerts/{guestId}/{photoId}
                                ▼
                    Downstream notifier (Email / SMS / WhatsApp)
```

---

## Core Flows

**1. Registration** — Guest uploads a reference selfie → indexed in **Rekognition** collection.

**2. Event upload** — Photographer uploads event photos → each photo is searched against the collection.

**3. Fan-out** — For every matched guest:
   - Write `notification/{guestId}_{photoId}.json` to S3
   - Publish to Solace `wedding/alerts/{guestId}/{photoId}`
   - Payload carries the guest's name, contact method, and a **shortened** presigned URL

**4. Delivery** — Subscribers (in-app SMTP, Twilio, or external) consume the topic and deliver.

---

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| Frontend | React + Vite + TypeScript | Guest registration, photo upload, admin |
| Backend | Express + TypeScript | API, orchestration, recognition pipeline |
| Storage | AWS S3 | Photos, metadata, notification payloads |
| Vision | AWS Rekognition | Face indexing + multi-face search |
| Event bus | Solace PubSub+ | Decoupled, topic-routed notifications |
| Delivery | Nodemailer / Twilio | Email, SMS, WhatsApp |
| Utility | TinyURL | Short, share-friendly presigned URLs |

---

## Why This Design

- **Event-driven** — the recognition pipeline doesn't know or care who delivers the notifications.
- **Topic-per-recipient** — `wedding/alerts/{guestId}/{photoId}` makes per-guest filtering trivial.
- **Two delivery paths** — direct Solace publish + S3 drop, so any consumer (push or pull) plugs in.
- **Resilient** — S3 / Rekognition / Solace / shortener each fail soft; the upload pipeline keeps going.

**Next:** persistent guest store, batched delivery, opt-out flow, deployable shortener for stable links.
