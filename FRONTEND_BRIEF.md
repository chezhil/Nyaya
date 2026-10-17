# Frontend rework brief

For our fourth team member ([@NIGHTFALLwarrior666](https://github.com/NIGHTFALLwarrior666)). Written 17 Oct 2026 by Chezhil.

**Goal:** make the NYAYA dashboard easier to read and more appealing **without changing what it says**. Every number
on it comes from the live engine on IBM LinuxONE, and the judges will check them. This is a visual and usability
rework, not a rewrite of the product.

**When:** after the submission freeze (the working demo comes first). Work on your own branch and open a PR into
`main`; Chezhil reviews and merges. Coordinate with Aaditya ([@AsteroidHH](https://github.com/AsteroidHH)), who built
the current dashboard and owns `dashboard/` and `docs/`.

## 1. What NYAYA is (30 seconds)

In floods and cyclones, displaced people pay at 2 AM from relief camps on borrowed phones, and fraud engines freeze
their accounts. NYAYA chooses between three outcomes for each payment:

- **RELEASE**: pay in full.
- **REVIEW**: send a survival stipend now (Rs 3,000), hold the rest in escrow for up to 48 h, then release it
  automatically unless an analyst confirms fraud.
- **HOLD**: block it (a mule ring or clear fraud).

The headline the dashboard must make obvious: **victims left with Rs 0: legacy engine 22.5% → NYAYA 0.06%** on a
10,000-payment held-out test. Background: [`README.md`](README.md); every measured number and its caveats:
[`models/MODEL_CARD.md`](models/MODEL_CARD.md).

## 2. How to see and run it

| Way | How | When to use |
|---|---|---|
| Live site | http://148.100.109.13:8000 (only while port 8000 is open on the server) | See the real thing |
| Your local copy against the live API | `cd dashboard && python3 -m http.server 5500`, open http://localhost:5500, click the settings button at the top right (tooltip "Configure Backend API URL") and set it to `http://148.100.109.13:8000`. The API allows cross-origin calls | Day-to-day work |
| Fully offline | Same local server with no API reachable: the dashboard falls back to `dashboard/fixtures/*.json` (real recorded responses) and labels them "recorded" | Working without the server |

No build step: it's plain HTML + JavaScript, served by the FastAPI app from `dashboard/`. **You don't need access to
the LinuxONE server, SSH keys or any Python setup for frontend work**: a browser, Git and any static file server are enough.

## 3. What's there now

| File | What it does |
|---|---|
| `dashboard/index.html` (≈790 lines) | Layout for the header and the 4 tabs. Tailwind via CDN (`cdn.tailwindcss.com/3.4.17`) |
| `dashboard/app.js` (≈980 lines) | All logic: API calls (`apiFetchRaw` / `apiFetch`, offline fallback in `getData`), rendering, Chart.js 4.4.7 charts, `escapeHtml` |
| `dashboard/styles.css` (≈100 lines) | Colour tokens on `:root` (dark theme only), scrollbars, small extras |
| `dashboard/fixtures/` | Recorded API responses for offline mode (see its README; Chezhil re-records them) |

**The four tabs and the API calls behind them** (contract: [`CONTRACTS.md`](CONTRACTS.md) §7):

| Tab | Shows | Endpoints |
|---|---|---|
| 1. Cyclone Replay | A 72-hour synthetic cyclone. Legacy engine on the left, NYAYA on the right, live counters incl. **victims left with Rs 0** | `POST /api/v1/replay` |
| 2. Transaction X-Ray & Notice | Six demo scenarios (e.g. Meena paying a pharmacy at 2 AM). The decision, fraud and mule scores, top-3 reasons, counterfactual, policy clause, Granite card, ledger hash, and the customer notice with a **தமிழ் / हिन्दी / EN** toggle | `GET /api/v1/scenarios`, `POST /api/v1/scenarios/{n}/run`, `POST /api/v1/evaluate`, `GET /api/v1/explain/{id}` |
| 3. Policy Console & Pareto | Sliders for the policy values, Pareto chart, results table (legacy / naive / NYAYA), fairness table, calibration | `GET /api/v1/policy`, `GET /api/v1/pareto`, `POST /api/v1/simulate` |
| 4. Analyst Queue & Red Team | REVIEW/HOLD queue with approve / deny / appeal, escrow-clock demo button, ledger verify, red-team table, NNPA timing | `GET /api/v1/queue`, `POST /api/v1/queue/{id}`, `POST /api/v1/queue/advance-clock`, `POST /api/v1/appeal/{id}`, `GET /api/v1/ledger/verify`, `GET /api/v1/redteam`, `GET /api/v1/system` |

The header strip reads `GET /api/v1/system` (s390x, NNPA, SELinux, latency).

## 4. What to improve (from a walk-through of the live site)

In rough priority order:

1. **Make the headline unmissable.** Tab 1 should open on one big comparison, "victims left with Rs 0: legacy X% vs
   NYAYA Y%", in plain words, with the live counters as supporting detail. Today it competes with a lot of small text.
2. **Lead with the decision in Tab 2.** The outcome (RELEASE / REVIEW / HOLD) and the money (paid now / held in
   escrow) should be the first and largest thing after you pick a scenario. Reasons, clause, Granite card and ledger
   hash come after, perhaps collapsible. Right now the counterfactual and policy text dominate the first screen.
3. **Plain language over internals.** Labels currently show plan references and paths ("(#20)",
   "data/scenarios/demo_scenarios.json", "(GET /API/V1/PARETO)", "Section A: Emergency Operations Analyst Queue",
   "HUMAN-IN-THE-LOOP GOVERNANCE"). Use short human titles ("Analyst queue", "Policy settings") and move technical
   detail into tooltips or a "How this works" toggle. Keep the source visible somewhere small: judges like seeing
   that a number is live.
4. **Calm the header.** The telemetry strip (arch, kernel, NNPA, CPACF, OpenSSL, SELinux, latency) is tiny
   monospace text. Turn it into a few clear badges (e.g. "IBM LinuxONE · s390x", "Model B on Telum NNPA",
   "Ledger verified") with details on hover or in tab 4.
5. **Readable type and contrast.** Less monospace, larger body text, stronger contrast for muted text (check WCAG AA).
   One consistent colour meaning everywhere: RELEASE green, REVIEW amber, HOLD red; legacy grey, NYAYA brand blue.
6. **Charts that read at a glance.** Clear titles that state the finding, labelled axes with units (Rs, %), legacy vs
   NYAYA in consistent colours, no chart-junk.
7. **The customer notice as a phone mock-up** that looks like a real SMS / app notification, with the language toggle
   on it. The Tamil and Hindi need fonts that render well (e.g. Noto Sans Tamil / Noto Sans Devanagari from Google
   Fonts).
8. **Works on a laptop projector and a phone.** Test at 1280×720 and 375 px wide; no horizontal scroll.
9. Optional: a light theme, a short guided "demo mode" that walks through Meena → clinic → syndicate → replay.

## 5. Rules that must not break

These come from [`AGENTS.md`](AGENTS.md) and from what we promise judges. If a change would break one, ask first.

- **No invented numbers.** Every figure comes from an API response or a recorded fixture. Never hard-code a metric,
  outcome or "example" number in the UI, even as a placeholder.
- **Keep the honest caveats visible**, not hidden in fine print:
  - Model B *runs* on the Telum NNPA but is **measured slower than CPU** at this size. Never say "accelerated"/"faster".
  - The fairness target (≤ 1.25 across income bands) is **not met**; the table must still show it.
  - Offline data must stay labelled "recorded", and live data "live".
- **Escape everything** that comes from the API before putting it in `innerHTML` (use `escapeHtml`). No raw IDs beyond
  the masked ones the API already returns.
- **Notice texts are written by native speakers** (`docs/notices.json`). Don't edit or machine-translate them; style
  them only.
- **Don't change the API contract.** If you need a new field or endpoint, ask Chezhil; the backend is in `api/`.
- **Stay a static site:** HTML + CSS + vanilla JS (or a framework only if its output is committed static files that
  FastAPI can serve from `dashboard/`). External scripts only from `cdnjs.cloudflare.com`, `cdn.jsdelivr.net/npm/`,
  `unpkg.com` or `cdn.tailwindcss.com`, pinned to an exact version. No secrets, tokens or server addresses beyond the
  public URL above in the code.
- **Analyst actions may need a token** if we turn it on (`X-Analyst-Token`; the dashboard already prompts for it on
  401). Keep that flow working.

## 6. Done means

- [ ] All four tabs work against the live API **and** in offline mode, with no console errors.
- [ ] The headline (victims left with Rs 0, legacy vs NYAYA) is the first thing a visitor understands.
- [ ] Every number on screen still matches the API/fixture it came from (spot-check against `models/MODEL_CARD.md`).
- [ ] RELEASE / REVIEW / HOLD colours and wording are consistent across tabs.
- [ ] Tamil and Hindi notices render correctly; the language toggle works.
- [ ] Readable at 1280×720 and at 375 px wide; text contrast passes WCAG AA.
- [ ] The NNPA and fairness caveats are still on screen.
- [ ] Before/after screenshots of each tab in the PR description.

## 7. Workflow

1. Accept the repo invite, then `git clone git@github.com:chezhil/Nyaya.git && cd Nyaya && git checkout -b nightfall-frontend`.
2. Edit only `dashboard/` (and `dashboard/fixtures/` only if a fixture's shape is genuinely missing something; ask first).
3. Small commits (`feat(dashboard): ...`), push, open a PR into `main` with screenshots. Don't push to `main` directly.
4. If you use an AI coding assistant, point it at `AGENTS.md`, `CONTRACTS.md` and this file, and review every diff
   yourself before committing.

Questions: Chezhil (backend, API, repo), Aaditya (current dashboard, notices, docs).
