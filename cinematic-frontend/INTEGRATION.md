# Abishek's cinematic frontend: how it is integrated

Source: `cinematic-frontend/NYAYA-ABISHEK-FINAL-FRONTEND.zip` on branch `abishek-cinematic-frontend` (commit b80a93c,
18 Oct 2026). Integrated on branch `abishek-frontend-integration`; the zip itself is not committed here.

## What the API now serves (FastAPI mounts `dashboard/` at `/`)

| URL | File | What it is |
|---|---|---|
| `/` | `dashboard/index.html` | Five-scene cinematic landing page (`cinematic.css`, `cinematic.js`, `camera-scroll.js`, `scroll-story.js`, `audio-engine.js`, `assets/`). "Explore dashboard" opens the dashboard in a dialog |
| `/dashboard.html` | `dashboard/dashboard.html` | The 4-tab dashboard, restyled (`command-center.css`, `command-center-v2.css`), same element ids and handlers |
| `/fixtures/*.json` | unchanged | Recorded responses for offline mode; the landing page reads `fixtures/simulate.json` for its headline and labels it "recorded on LinuxONE" |

## What changed versus main

- `dashboard/app.js`: only startup changed. It waits for scenario 1, sets `window.nyayaDashboardReady`, and opens the tab named in the URL hash (e.g. `dashboard.html#tab-xray`). API calls, escaping, offline fallback and the analyst-token flow are untouched.
- `dashboard/vendor/`: local copies of Tailwind 3.4.17 and Chart.js 4.4.7, checked byte-identical (SHA-256) to `cdn.tailwindcss.com/3.4.17` and `cdn.jsdelivr.net/npm/chart.js@4.4.7`, so the dashboard also works without internet.
- Line endings normalised to LF (the zip had CRLF). `styles.css` and fixtures are otherwise identical to main.
- Not served, kept here for reference: Abishek's reports (`reports/`), his browser/contract checks (`tests/`), `START-NYAYA.cmd`, `SHA256SUMS.txt` (hashes of the zip as delivered, before the LF normalisation).

## Verified (18 Oct 2026)

- Served by the real FastAPI app: `/`, `/dashboard.html`, scripts, vendor files, images and fixtures all return 200.
- Landing page: no console errors; headline reads "22.5% → 0.06%" from the recorded suite.
- Dashboard pointed at the live LinuxONE API (`A-xgb-iso-1+B-mlp-1`, real): header shows LIVE s390x, the Cyclone Replay runs (legacy 21.11% vs NYAYA 0.00% victims left with Rs 0), all API calls succeed, no console errors.
- Not yet deployed to the server pod: that needs this branch merged and `git pull` on the server.

## Fix, 18 Oct 2026: motion revealed baked mock-up text; panel spacing

- `assets/reference.png` (a full-page design mock-up with invented figures such as "300M+ people affected" and
  "248,390 transactions today") is removed, with every CSS reference to it.
- `assets/human-story.webp` is a crop of that mock-up and still carries its text, including a made-up customer quote.
  The cards were hiding it, but with motion on the image and the cards move separately, so the text showed through.
  A mask layer now sits inside the image's own layer (`.people .bake-mask`), so it moves with the image. On phones,
  where no card covers the photo and its baked headline crosses the mother's face, that one photo is not shown.
  A clean replacement image would let us drop both.
- `camera-scroll.js`: smaller movements (background ±24 px, text ±12 px, cards ±8 px), and the zoom always covers the
  shift around each scene's origin, so no empty edge appears.
- Text panels get padding on every side (was 0 on the left); map labels are compact chips that no longer overlap.
