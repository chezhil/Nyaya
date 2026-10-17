# NYAYA contracts

The only interfaces people depend on. Change one only after a message in the team chat and a note here.

## Ownership

| Folder | Owner · agent | Notes |
|---|---|---|
| `api/` `ledger/` `explain/` `deploy/` | Chezhil · Claude session A | FastAPI, feature store, MCI worker, ledger, explainer, pod |
| `data/` | Chezhil · Claude session B | Synthetic generator, schema, OpenFEMA mapping, demo fixtures |
| `models/` `engine/` | Kaustub · Claude Code | Model A, calibration, Model B, conformal, harm engine, counterfactuals |
| `sim/` | Kaustub · Codex | 10k suite, baselines, sensitivity, fairness, red team |
| `notebooks/` | Kaustub · Antigravity | 01–05 |
| `dashboard/` | Aaditya · Antigravity | Static HTML/JS, 4 tabs |
| `docs/` | Aaditya (hand + Antigravity) | Policy doc, notices, README, model card, Q&A |
| root files (`AGENTS.md`, `CONTRACTS.md`, `CLAUDE.md`, `pytest.ini`, `.gitignore`) | Chezhil | ask before editing |

Branches: `chezhil-platform`, `kaustub-ml`, `aaditya-dashboard`. PR into `main`; Chezhil merges at each gate.

## 1. Data (Chezhil → Kaustub, 12:00)

Generator: `python -m data.generate --out ~/shared/data --tag v1` (run inside the `notebook` container).
Files (gzip CSV, **not parquet**: the IBM image has no pyarrow):

| File | Grain | Use |
|---|---|---|
| `nyaya_v1.csv.gz` | one row per payment | Model A training, suite, replay |
| `accounts_v1.csv.gz` | one row per account | static recipient features, income band |
| `recipients_v1.csv.gz` | one row per (payment → recipient) snapshot | Model B training |

Columns and feature definitions: **`data/schema.md`** (the source of truth). Online features are computed by the
same code (`data/features.py`), so training and serving can't drift.

## 2. Model artifacts (Kaustub → Chezhil, 13:00)

All written on the LinuxONE server to `~/shared/nyaya/artifacts/` (git-ignored).

| File | Content |
|---|---|
| `model_a.json` | `xgboost.Booster.save_model()` JSON, binary:logistic |
| `model_a_meta.json` | `{"version": str, "features": [names, in training order], "legacy_threshold": float \| null}` — features must come from `data/schema.md` §Model A features. `legacy_threshold` = raw-score threshold at 1% FPR on validation for the legacy baseline |
| `calibration.json` | isotonic regression: `{"x": IsotonicRegression.X_thresholds_, "y": IsotonicRegression.y_thresholds_}` |
| `conformal.json` | `{"qhat": float, "alpha": 0.1}` — split conformal on calibrated P(fraud), score = 1 − p(true label). Set = {legit if p_fraud ≤ qhat} ∪ {fraud if 1 − p_fraud ≤ qhat}. **Any set that is not exactly one label (empty or both) means "uncertain" → REVIEW.** With two labels a set can only hold both when qhat ≥ 0.5; an accurate model at 90% coverage gives qhat < 0.5, so its uncertain cases come out empty |
| `model_b.pt` | `torch.save(model.state_dict())` of exactly `nn.Sequential(nn.Linear(7,32), nn.ReLU(), nn.Linear(32,16), nn.ReLU(), nn.Linear(16,1))`, output = logit |
| `model_b_meta.json` | `{"version": str, "features": [7 names from data/schema.md §Model B], "mean": [7], "std": [7]}` (standardise before the forward pass) |

The API (`api/bundle.py`) loads these. If any are missing it falls back to `StubBundle` and every response says
`"model_version": "stub-…"`.

## 3. Engine (Kaustub `engine/` → API)

```python
# engine/__init__.py must export:
def decide(scores: dict, tx: dict, policy: dict) -> dict:
    """scores = {"p_fraud": float, "p_mule": float, "conformal_set": ["legit"] | ["fraud"] | ["legit","fraud"] | []}
    (empty or two labels = uncertain)
    tx = the /evaluate request after defaults are filled (data/schema.md payment columns)
    policy = api/policy_defaults.json merged with any request overrides
    returns {"decision": "RELEASE"|"REVIEW"|"HOLD", "release_now": float, "escrow": float,
             "harm_delta": float, "h_fraud": float, "h_hold": float}"""

def counterfactual(row: dict, score_fn, policy: dict, tx: dict) -> dict | None:
    """row = Model A feature dict; score_fn(row) -> scores dict (as above).
    returns {"feature": str, "from": float, "to": float, "new_decision": str, "text": str} or None"""

ENGINE_VERSION: str
```
Until `engine/` exists the API uses `api/fallback_policy.py` (the §5.6 table, nothing else) and reports
`"engine_version": "api-fallback"`.

## 4. Sim hooks (Kaustub `sim/` → API → dashboard, shapes frozen 16:30)

```python
# sim/__init__.py may export any of:
def simulate(ctx, params: dict) -> dict   # POST /api/v1/simulate
def pareto(ctx, params: dict) -> dict     # GET  /api/v1/pareto
def redteam(ctx, params: dict) -> dict    # GET  /api/v1/redteam
```
`ctx` gives `ctx.bundle.score(tx) -> scores`, `ctx.bundle.score_legacy(tx)`, `ctx.decide(scores, tx, policy)`,
`ctx.policy` (dict). If a hook is missing, the API serves `artifacts/sim/<name>.json` if present, else HTTP 503.
JSON shapes are owned by Kaustub and pasted below when frozen.

## 5. Policy parameters (`api/policy_defaults.json`)

`alpha, beta, tau, theta_mule, stipend_cap, escrow_hours, urgency_by_category`. Aaditya replaces `beta` and
`stipend_cap` with cited official figures (§2 of the plan) and fills in the `sources` field.

## 6. Content files (Aaditya → API)

| File | Format |
|---|---|
| `docs/relief_policy.md` | Clauses as `### <id> <title>` headings (e.g. `### 4.2 Survival stipend`) followed by the clause text. BM25 indexes each clause |
| `docs/notices.json` | `{"RELEASE": {"en": "...", "ta": "...", "hi": "..."}, "REVIEW": {...}, "HOLD": {...}}`, slots: `{amount}` `{release_now}` `{escrow}` `{hours}` (₹ added by the template) |

If missing, the API uses `explain/fixtures/` (English only, marked `"source": "fixture"`). We never machine-translate.

## 7. HTTP API (Chezhil → Aaditya)

Base `http://<host>:8000`. Dashboard is served at `/` from `dashboard/`.

`POST /api/v1/evaluate` — request = payment columns from `data/schema.md` (only `sender_id`, `recipient_id`,
`amount` required). Response:
```json
{"tx_id","decision","release_now","escrow","p_fraud","p_fraud_raw","p_mule","conformal_set","harm_delta",
 "reasons":[{"feature","value","contribution"}×3],"counterfactual","policy_clause":{"id","title","text","score"},
 "notice":{"en","ta","hi","source"},"card_template","explain_id","ledger_hash","latency_ms",
 "model_version","engine_version","recipient_features":{...}}
```
Also: `POST /api/v1/events` (feed payments into the feature store, no decision) · `GET /api/v1/explain/{id}` ·
`POST /api/v1/replay` · `POST /api/v1/simulate` · `GET /api/v1/pareto` · `GET /api/v1/redteam` ·
`POST /api/v1/appeal/{id}` · `GET /api/v1/queue` · `POST /api/v1/queue/{id}` (`{"action":"approve"|"deny","analyst":str}`) ·
`GET /api/v1/ledger/verify` · `GET /api/v1/system` · `GET /api/v1/scenarios` · `POST /api/v1/scenarios/{n}/run`.
