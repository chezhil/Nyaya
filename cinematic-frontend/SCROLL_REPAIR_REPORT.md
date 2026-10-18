# NYAYA — Cinematic Scroll Motion Repair

This is an additive repair to **NYAYA-CINEMATIC-DASHBOARD-FINAL**. It restores strong, scene-wide cinematic motion while retaining Astra's successful word-by-word appearance/disappearance effects.

## What changed

- Added `dashboard/camera-scroll.js`: dedicated scroll-linked camera movement for all five scenes (zoom, directional travel, ambient detail parallax and foreground/HUD depth). Motion works with regular mouse-wheel/touchpad scrolling in both directions.
- Updated `dashboard/index.html` to load the additional script.
- Appended contained, desktop-only cinematic motion CSS to `dashboard/cinematic.css`. On mobile, the source image and layout are left stable for clarity and performance. Reduced Motion and Pause Motion remain supported.
- Added `START-NYAYA.cmd` for a one-step Windows preview using Node/npx and port **8769**.

## What did NOT change

- **All seven files under `dashboard/assets/` are byte-for-byte unchanged**, including all five approved background images. No re-generation, upscaling, resizing or recompression. Existing image-resolution limitations remain.
- **Chezhil's dashboard and its integration code are unchanged:** `dashboard/dashboard.html`, `dashboard/app.js`, `dashboard/styles.css`, `dashboard/command-center.css`. No backend source included or modified.
- Existing `dashboard/cinematic.js`, `dashboard/scroll-story.js`, `dashboard/audio-engine.js`, buttons, dashboard link and fixtures remain unchanged.

## Tests and limitations

- 18 static/source checks and 28 dashboard contract checks passed. JavaScript syntax checks passed for scroll, cinematic and camera scripts.
- Playwright Chromium tested desktop (1440×900) and mobile (390×844), using an **in-memory page with the actual HTML, CSS, JS and embedded exact image assets**, because the container's browser administrator policy blocked navigating to the local HTTP server. This is a partial browser verification, **not** a full live HTTP integration test.
- Desktop measured camera transform after 420px of scrolling was different from its initial transform, proving the new camera movement responds to scroll rather than just text opacity. Text reveal spans remained present. Dashboard modal opened and closed. No captured JS exceptions or horizontal overflow on either viewport.
- Live IBM Z/LinuxONE backend interaction was **not tested**; the existing recorded-data fallback remains.
- **You should still verify the complete visual experience directly in Chrome on your Windows laptop.** If an effect is unsuitable, you can remove `dashboard/camera-scroll.js` from `index.html` and the appended CSS without affecting the underlying dashboard.

## Open on Windows

Extract the ZIP, double-click `START-NYAYA.cmd` (requires Node.js/npm as already installed on your laptop), leave the command window open, then visit `http://127.0.0.1:8769/index.html` in Chrome. Alternatively, open Command Prompt in the extracted folder and run:

```cmd
npx.cmd --yes http-server dashboard -p 8769 -c-1
```

Use a new port to avoid loading earlier versions cached at ports 5500/8766/8768.
