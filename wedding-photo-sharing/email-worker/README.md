# Email Worker

Standalone Solace queue consumer that delivers wedding-photo notifications by email. Decoupled from the backend so SMTP delivery can scale, fail, or be replaced independently.

See the [project README](../README.md) for the system-wide architecture.

## How it fits

```
backend  ──publish──►  wedding/alerts/photos/email/{guestId}/{photoId}
                              │
                              ▼ (topic subscription on the queue)
                       EMAIL_SOLACE_QUEUE
                              │
                              ▼ guaranteed-message consumer
                        email-worker  ──SMTP──►  recipient inbox
```

The backend never calls SMTP directly for the email channel; it just publishes. The worker acks each message after `nodemailer.sendMail` resolves; on SMTP failure the message is not acked and the broker redelivers per its policy.

## Broker prerequisite

Before the worker can do anything useful, on the Solace broker:

1. Create a queue named after `EMAIL_SOLACE_QUEUE` (default: `wedding_alerts_email_queue`)
2. Add a topic subscription on that queue: `wedding/alerts/photos/email/>`
3. Make the queue *Exclusive* and ensure the configured Solace user can consume from it

## Run

```bash
npm run dev    --workspace=email-worker   # ts-node-dev with --respawn
npm run build  --workspace=email-worker
npm start      --workspace=email-worker
```

## Configuration

See [`.env.example`](./.env.example). The worker loads its own `.env` first and falls back to `../backend/.env`, so for local dev keeping one `.env` in the backend folder works.

Required: `SOLACE_*`, `EMAIL_SOLACE_QUEUE`, `EMAIL_USER`, `EMAIL_PASS`. The worker will exit at startup if any are missing.

## Message contract

The worker expects this JSON payload on the queue (published by the backend on `wedding/alerts/photos/email/{guestId}/{photoId}`):

```ts
{
  payload: {
    guestName: string;
    contactMethod: {
      channel: 'email';
      value:   string;   // recipient email
    };
    photoUrl:          string;   // S3 URL (informational)
    photoPresignedUrl: string;   // SHORT URL — used as click-through link
    photoImageUrl?:    string;   // FULL presigned URL — used as <img src>
  };
}
```

`photoImageUrl` exists because most email clients won't follow redirects when fetching `<img src>`, so the shortened URL is unsafe there. If the field is missing the worker falls back to `photoPresignedUrl` (older messages).

## Logging

On each successful send the worker logs:

```
[Email][SMTP] to=<addr> messageId=<id> accepted=[...] rejected=[...] response=<smtp response>
```

This is the most useful place to look when "I didn't receive the email" — `accepted`/`rejected` are what the SMTP server actually said.
