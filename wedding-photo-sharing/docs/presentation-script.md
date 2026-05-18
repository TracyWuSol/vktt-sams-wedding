# Presentation Script — Wedding Photo Sharing

Approx. 5 minutes total. Each block is the spoken script for that slide.

---

## Slide 1 — Title

> Hi everyone. I want to walk you through a small system we built for an obvious-but-painful wedding problem: getting photos to the right guests, automatically. It's a React frontend, an Express backend, and it leans on AWS for storage and vision, and Solace PubSub+ as the event spine. The whole thing runs as a single repo and starts with one `npm run dev`.

---

## Slide 2 — The Problem

> Picture a wedding: two photographers, a hundred guests, three thousand photos by the end of the night. Sorting through them by hand to send each guest their pictures is a job nobody wants. Group chats are noisy and impersonal. Most guests just give up and leave without a single photo of themselves.

> So we set ourselves a sharper goal. Every guest should automatically receive the photos they appear in, within seconds of the photographer pressing upload. No manual tagging. No "ask me later." Just delivered.

---

## Slide 3 — High-Level Architecture

> Here's the shape. The React frontend handles two flows: guests register a selfie, and photographers upload event photos. Both go through the Express backend.

> When an event photo arrives, the backend stores it in S3 and immediately asks Rekognition to find every face it knows in that picture. Rekognition returns a list of matched guests.

> From there the backend fans out in two ways. It writes a small JSON payload into a `notification/` folder in S3 — one file per matched guest. And it publishes the same alert to a Solace topic that's structured as `wedding/alerts/` followed by the guest ID and photo ID. Anyone subscribed to those topics — our own SMTP service, a Twilio worker, or a future mobile push service — picks them up and delivers.

---

## Slide 4 — Core Flows

> Let me make those flows a bit more concrete.

> Step one is registration. A guest uploads a selfie, and we index it into a Rekognition collection. That gives us a face ID we hang on the guest record.

> Step two is the event upload. Photographer drops in photos. For each one, we run a multi-face search against the collection.

> Step three is the interesting part — the fan-out. For every guest we matched, we do two things in parallel: drop a JSON file in S3 under `notification/{guestId}_{photoId}.json`, and publish to Solace at `wedding/alerts/{guestId}/{photoId}`. The payload carries the guest's name, their contact method — email or phone — and a presigned download URL that we then shorten through TinyURL so it's friendly to paste into an SMS or WhatsApp.

> Step four is delivery. Anything that subscribes to those topics or watches that S3 prefix can be the notifier. We have built-in email, SMS, and WhatsApp paths, but the system doesn't actually care — it just publishes.

---

## Slide 5 — Tech Stack

> Quick rundown of what we used and why.

> Frontend is React with Vite — fast dev loop, nothing exotic. Backend is Express in TypeScript so we share types with the frontend. AWS S3 holds the photos themselves and the notification payload JSONs. Rekognition does the actual face matching — it handles the vision problem so we don't have to.

> Solace PubSub+ is the event broker tying it all together. We chose it because the topic hierarchy gives us per-guest, per-photo routing for free — no custom routing logic in our code. Nodemailer and Twilio handle the delivery, and TinyURL shortens our presigned URLs so the messages don't look like spam.

---

## Slide 6 — Why This Design

> Three things to call out about why we set it up this way.

> First, it's event-driven. The recognition pipeline doesn't know who's sending the notifications. That means we can swap delivery channels — add Slack tomorrow, drop SMS next week — without touching the recognition code.

> Second, the topic structure is one-per-recipient-per-photo. That makes filtering trivial: a downstream service that only cares about one specific guest just subscribes to `wedding/alerts/{theirId}/>`. No fan-out logic to write.

> Third, every external dependency fails soft. If S3 is down for a guest's metadata, we still publish to Solace. If Solace is offline, we log it and the upload still succeeds. If TinyURL doesn't respond, we send the long URL. Nothing in this pipeline takes the whole system down.

> A few things on the roadmap: a real persistent guest store instead of the in-memory map we use today, batching delivery so a guest gets one digest instead of fifty pings, an opt-out flow, and replacing TinyURL with a shortener we own so the links stay alive long-term.

> That's the system. Happy to take questions.
