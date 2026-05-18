# Backend — Wedding Photo Sharing

Express API that owns the guest registry, runs face recognition on uploaded photos, and publishes alerts to Solace.

See the [project README](../README.md) for the system-wide architecture and quickstart.

## Run

```bash
npm run dev    --workspace=backend   # ts-node-dev with --respawn
npm run build  --workspace=backend   # → dist/
npm start      --workspace=backend   # node dist/index.js
npm test       --workspace=backend
```

Default port: `4000` (override with `PORT`).

## Routes

### Guests
| Method | Path | Body / Notes |
|---|---|---|
| `POST` | `/api/guests` | multipart: `name`, `email`, `phone`, `preferredChannel`, `photo` (selfie) |
| `GET`  | `/api/guests` | List all guests |
| `GET`  | `/api/guests/:id` | Single guest |
| `PATCH`| `/api/guests/:id` | JSON: `email?`, `phone?` (only these are editable) |
| `DELETE`| `/api/guests/:id` | Removes guest record + face from Rekognition |
| `GET`  | `/api/guests/:id/notifications` | Notification history for one guest |

### Photos
| Method | Path | Body / Notes |
|---|---|---|
| `POST` | `/api/upload-photos` | multipart: `uploadedBy`, `photos[]`. Triggers Rekognition + Solace fan-out |
| `GET`  | `/api/upload-photos` | All session photos |
| `GET`  | `/api/upload-photos/:id/result` | Recognition result |

### Admin / Status
| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/admin/reset` | Wipe guest store + Rekognition collection |
| `GET`  | `/api/admin/faces` | Diagnose stale-face mismatches |
| `GET`  | `/api/status` | Counters used by the UI navbar |

## Solace topics published

```
wedding/s3/photos/uploaded
wedding/recognition/completed
wedding/alerts/{guestId}/{photoId}
wedding/alerts/photos/email/{guestId}/{photoId}   ← consumed by email-worker
wedding/notifications/send
```

For email and Line, the backend only publishes — actual delivery is done by separate worker services consuming Solace queues (the email-worker is implemented; a line-worker is the same shape but not yet built). SMS still goes out in-process via Twilio.

## Persistence

- `data/guests.json` — guest records survive restarts (gitignored; contains PII)
- Photos, recognition results, and notification history are session-only and reset on restart (re-derivable from S3/Rekognition)

## Configuration

See [`.env.example`](./.env.example). The backend exits at startup if required vars are missing.

## AWS prerequisites

- An S3 bucket (set `AWS_S3_BUCKET`); the bucket policy must allow `PutObject`, `GetObject`, and presigned URL generation for the configured IAM identity
- Rekognition permissions: `rekognition:CreateCollection`, `IndexFaces`, `SearchFacesByImage`, `DetectFaces`, `DeleteFaces`, `DeleteCollection`, `DescribeCollection`, `ListFaces`
- The Rekognition collection is created automatically on first start
