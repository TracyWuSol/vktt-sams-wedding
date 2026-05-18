# Frontend — Wedding Photo Sharing

React + Vite UI for the wedding photo system. Two pages: admin (register guests) and upload (drop event photos).

See the [project README](../README.md) for the system-wide architecture.

## Run

```bash
npm run dev    --workspace=frontend   # http://localhost:5173
npm run build  --workspace=frontend   # → dist/
npm run preview --workspace=frontend
```

The Vite dev server proxies `/api/*` to `http://localhost:4000` (the backend), so the two run side-by-side with no CORS setup.

## Pages

- `/` — **Admin**: register a guest with a reference photo, list/edit/delete existing guests, reset the registry
- `/upload` — **Upload Photos**: drop event photos, see Rekognition matches and per-guest notification status inline

## Styling

A single `src/index.css` with CSS custom properties for the dark wedding theme. Fonts are loaded from Google Fonts (`Cormorant Garamond` for headings, `Inter` for body).

## Component map

```
src/
├── App.tsx                  # router + navbar
├── pages/
│   ├── AdminPage.tsx        # guest registration + list
│   └── GuestPage.tsx        # event photo upload + results
├── components/
│   ├── GuestCard.tsx        # inline edit / delete per guest
│   ├── PhotoDropzone.tsx    # drag-and-drop file picker
│   └── StatusBadge.tsx      # loading / success / error chips
├── services/api.ts          # fetch wrappers for the backend
└── types/                   # shared TS types
```
