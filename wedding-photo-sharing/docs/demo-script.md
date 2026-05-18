# Live Demo Script — Wedding Photo Sharing

A 3–5 minute spoken walk-through. Each beat is the narration; stage directions live in [square brackets]. Total target: **~4 minutes**, leaving ~30 seconds of headroom for face-recognition latency and any browser stalls.

## Before you go live

- Two browser tabs already open: **Admin** (`/`) and **Upload Photos** (`/upload`)
- A third tab open on your **email inbox** (the address you'll register a guest with)
- Your phone (or a phone-mockup screenshot) showing **Line** ready to show on screen
- Two guest selfies on the desktop, named so you can find them fast (e.g. `alex.jpg`, `sam.jpg`)
- Three group photos that contain those two faces (`group-1.jpg` … `group-3.jpg`)
- Reset the registry beforehand so you start clean (Admin → Reset All)

---

## Beat 1 — The setup [~20 sec]

> "Imagine the morning after a wedding. The photographers have shot two thousand photos. Every guest wants the ones they're in — and nobody wants to scroll through a Dropbox folder of two thousand strangers. So we built this: register your face once at the door, and the photos of you get delivered to whatever channel you prefer, automatically, within seconds of being uploaded. Let me show you."

[Have the Admin page already on screen.]

---

## Beat 2 — Register the first guest [~50 sec]

> "We start at the registration desk. A guest gives their name, contact details, and one clear selfie. They also pick how they'd like to be reached — email, or in this demo, Line. Then they tick a consent box, because the system stores a face vector and we want to be explicit about that."

[Fill in name, email, phone. Choose **Email** as the preferred channel. Drop the first selfie into the dropzone. Tick the consent checkbox. Click **Register Guest**.]

> "You can see the guest appear in the registry on the right, with their selfie shown as the avatar. The face has now been turned into a mathematical fingerprint and stored, ready to be matched."

---

## Beat 3 — Register a second guest [~30 sec]

> "We'll register one more, this time someone who prefers Line for messages. In a real wedding this would be handled at the welcome table — a tablet, a guest, thirty seconds, done."

[Fill in the second guest. Choose **Line** as the preferred channel. Drop the second selfie. Consent. Register.]

> "Two guests in the registry. Notice their avatars are their actual faces — the system already knows what they look like."

---

## Beat 4 — Photographer uploads event photos [~45 sec]

[Switch to the **Upload Photos** tab.]

> "Now we switch hats. The photographer is back from the ceremony with their memory card. They drag the photos into the browser — no tagging, no folders, no spreadsheet. Just upload."

[Drag the three group photos into the dropzone. Click **Upload**. Talk while it processes — Rekognition typically takes a few seconds per photo.]

> "Behind the scenes, every photo is being scanned for faces, and each face is being checked against everyone we just registered. This whole pipeline is event-driven, so the moment a match is found a notification message goes out — the guest doesn't have to wait for the photographer to finish the whole batch."

---

## Beat 5 — Recognition results [~30 sec]

[Point at the results panel as it fills in.]

> "Here are the results. For each photo, the system tells us which registered guests it found, with a confidence score, and whether they've been notified. Three photos, two guests, six matches — and you can see every single one is marked as 'Notified'."

---

## Beat 6 — The notifications land [~50 sec]

[Switch to the email inbox tab.]

> "Let's go look at one of those notifications. Here's the email — addressed to the guest by name, with the actual photo embedded right in the message and a link to download the full-resolution version. No app to install, no account to create — they just open the email."

[Switch to the Line view.]

> "And for the second guest, who preferred Line, the same alert lands as a Line message. Same payload, different channel. The point of this design is that we don't care what app you live in — the system fans out to whichever way you've chosen to be reached. Today it's email and Line; tomorrow we could add SMS, push notifications, WhatsApp, even a printer at the wedding venue."

---

## Beat 7 — Wrap [~20 sec]

> "So that's the flow. Register a face once. The photographer keeps shooting. Every guest who's actually in a photo receives it on their preferred channel within seconds — without the photographer or the couple having to lift a finger. Two thousand photos, hundreds of guests, fully sorted, before the bar even reopens."

[Pause. Take questions.]

---

## Time budget summary

| Beat | Target | Notes |
|---|---|---|
| 1 — Setup intro | 0:20 | Pure narration |
| 2 — First registration | 0:50 | Includes face indexing latency |
| 3 — Second registration | 0:30 | Move faster, you've shown the form |
| 4 — Photo upload | 0:45 | Recognition runs while you talk |
| 5 — Results | 0:30 | Just point at the screen |
| 6 — Notifications | 0:50 | Email + Line side-by-side |
| 7 — Wrap | 0:20 | One sentence, then questions |
| **Total** | **~3:45** | Leaves headroom for stalls |

## If something goes wrong

- **Recognition slow**: keep talking — describe the architecture out loud while the spinner runs
- **No matches found**: most often means you uploaded a photo that doesn't actually contain the registered face. Have a known-good "definitely contains both faces" photo as backup
- **Email doesn't arrive**: have a screenshot of a previous email ready to show; say "for reliability today I've staged the email tab" and switch to it
- **Line side fails**: same trick — a phone screenshot of a real previous Line message works fine
