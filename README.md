# NYAYA

Disaster-aware fraud decisions on IBM LinuxONE · IBM Z Datathon 2026 (Real-Time AI for Critical Decisions).

> Built during the official hackathon window (17–18 Oct 2026). No solution code was written before kickoff.

During a cyclone, flood victims pay from relief camps at 2 AM, on borrowed phones, far from home: exactly what fraud
engines are trained to freeze. A frozen account at that moment means no food, fuel or medicine. Fraud rings know this
and pose as victims. NYAYA decides each payment by **expected harm in rupees**, not by a fixed score cut-off, and adds
a third outcome between "pay" and "block":

| Decision | What the payer gets |
|---|---|
| **RELEASE** | the full amount |
| **REVIEW** | a survival stipend now (up to ₹3,000), the rest in encrypted escrow that auto-releases after 48 h unless an analyst confirms fraud; one-tap appeal |
| **HOLD** | nothing; mule-ring payees and clear fraud |

All data is synthetic (`data/generate.py`) or public (PaySim-style balances, OpenFEMA declarations). Results describe
the method on that data, not real-world accuracy.

## Results (measured on LinuxONE, 17 Oct 2026)

Independent 10,000-payment suite (`nyaya_eval`, never used for training or tuning; `models/MODEL_CARD.md`):

| | Legacy | Naive relaxed | NYAYA |
|---|---|---|---|
| Victims left with ₹0 | 22.5% (405 of 1,800) | 9.7% (175) | **0.06% (1, mule-flagged)** |
| Share of victims' money available immediately | 54.6% | 57.6% | 85.5% |
| Fraud leakage | ₹75.5 lakh | ₹76.4 lakh | ₹2.43 lakh |

Legacy = the same Model A without disaster context, HOLD above its 1% false-positive threshold. Read the model card
before quoting the leakage gap: it depends on that baseline definition. The victims-left-with-₹0 gap is the robust
headline.

What did **not** go our way, reported as measured:
- **Fairness**: the 1.25× max/min parity target across synthetic income bands is **not met** (legitimate payments:
  freeze ratio 1.30, REVIEW ratio 1.61).
- **Red team** (`sim/redteam.json`, detection = HOLD or REVIEW): base syndicate 93.8%, smurfing 80.4%, device spoofing
  83.5%, slow drip 77.0%. NYAYA weakens against every adaptation.
- **Telum NNPA**: Model B runs on the NNPA (`mule_device: nnpa`) but is **slower than the CPU** at this model size
  (p50 batch 1: 0.035 vs 0.026 ms; batch 10,000: 4.16 vs 1.70 ms; only batch 100 is slightly faster). No speed-up
  is claimed.
- **Zone rule** (`zone_hold_needs_mule`): it is what keeps victims off ₹0, and it costs about ₹1.76 lakh more
  account-takeover leakage on the independent file (model card, "Decision policy").
- **Granite** is slow and unreliable here: a card takes 17–21 s on this 3-vCPU VM and half of the demo cards fail the
  number check, so decisions never wait for it and the template is always shown first (see [Explanations](#explanations)).

Live service on the 3-vCPU VM (`docs/evidence/`): 2,000 `/evaluate` calls at concurrency 8 → 334.9 req/s, client p50
20.5 ms / p95 46.3 ms; OpenSSL on CPACF: SHA-256 4.26 GB/s, AES-256-GCM 12.31 GB/s (16 KB blocks); SELinux
Enforcing, rootless Podman; ledger chain verified.

Synthetic Chennai cyclone replay (`POST /api/v1/replay`, 72 h, 9,123 payments, 720 by displaced victims): victims
left with ₹0: legacy 152 (21.1%), NYAYA 0.

## How it works

```
payment ─► features (data/features.py, same code offline and online)
        ├► Model A  XGBoost + isotonic calibration + split conformal  → P(fraud), uncertain?
        ├► Model B  PyTorch MLP on the payee's 15–60 min graph (fan-in, forwarding, shared devices, MCI) → P(mule), on the NNPA
        └► engine/policy.py  H_fraud = P·amount,  H_hold = (1−P)·β·e^(α·severity)·urgency(category)
               HOLD if P(mule) ≥ θ or ΔH ≥ τ (inside a zone only the mule override can HOLD)
               REVIEW if uncertain or ΔH > −τ_review, and amount > cap   →  stipend now + escrow
               RELEASE otherwise
        ─► reasons (TreeSHAP top 3) · counterfactual · policy clause (BM25 over docs/relief_policy.md)
        ─► notice in Tamil / Hindi / English (docs/notices.json, written by people, never machine-translated)
        ─► SHA-256 hash-chained ledger, AES-256-GCM escrow records · analyst queue · auto-release after 48 h
```

β = ₹345 (one day of the Tamil Nadu rural wage, MoRD notification of 30 June 2026) and the ₹3,000 cap (half of the
₹6,000 Cyclone Michaung relief per family) are cited in `docs/policy.md` clause 5 and `api/policy_defaults.json`.

### Explanations

Granite 4.0 350M (llama.cpp, in its own container) rewrites a template card from **allow-listed, masked facts only**
(`explain/masker.py`); identifiers never reach the prompt, outputs are checked against the facts, and the template is
served whenever Granite is busy, slow or rejected. The card's `source` field says which one you are reading.

Measured on the VM (17 Oct): model load ≈ 1 s, then 17.5–20.5 s per card on 2 threads with the current
three-example prompt (13.4–15.7 s with the earlier two-example prompt). On the 6 demo scenarios Granite's card
passed the check for 1, 3 and 6 and was rejected (template shown) for 2, 4 and 5, each for a wrong amount. So `/evaluate` returns the decision and the template card immediately;
`GET /api/v1/explain/{id}` asks Granite with a 30 s budget (`NYAYA_GRANITE_TIMEOUT` in `deploy/pod.sh`), and the
dashboard shows Granite's card next to the template. One generation runs at a time; concurrent requests get the template.

Granite's wording is not reliable: on 17 Oct, for scenario 2 (REVIEW, ₹3,000 now + ₹22,000 escrow) it wrote that the
payment "was released in full". `check_output` only verifies numbers, so the dashboard shows the template first and
Granite's text below it as an unverified draft.

## Repository

| Folder | What | Owner |
|---|---|---|
| `api/` `ledger/` `explain/` `deploy/` `data/` | FastAPI service, ledger, explainer, pod, synthetic data | Chezhil |
| `models/` `engine/` `sim/` `notebooks/` | Models A/B, decision engine, evaluation suite, notebooks 01–05, model card | Kaustub |
| `dashboard/` `docs/` | 4-tab dashboard, policy, notices, FAQ | Aaditya |

Interfaces: `CONTRACTS.md`. Rules for code and agents: `AGENTS.md`. Evidence: `docs/evidence/`.

## Run it

On the LinuxONE server (rootless Podman, IBM's s390x Jupyter image, artifacts in `~/shared/nyaya/artifacts`):

```bash
cd ~/shared/nyaya && git pull --ff-only && deploy/pod.sh
curl -s http://127.0.0.1:8000/api/v1/system      # models "real", mule_device "nnpa", engine-1
```

The dashboard is served at `/`. Port 8000 is not opened to the internet; from a laptop:

```bash
ssh -N -L 8000:127.0.0.1:8000 <server>   # then open http://localhost:8000
```

Without the server, `cd dashboard && python3 -m http.server` shows the same tabs from responses recorded on LinuxONE
(`dashboard/fixtures/`, labelled "recorded").

Tests: `python -m pytest` (76 pass on the server). Reproducing the models and results: commands at the end of
`models/MODEL_CARD.md`.

Demo scenarios (`POST /api/v1/scenarios/{n}/run`, live on 17 Oct): 1 Meena at a relief-camp pharmacy at 2 AM →
RELEASE; 2 clinic payment to a new payee, severity 5 → REVIEW (₹3,000 now, ₹22,000 escrow); 3 syndicate spoofing the
zone → HOLD (mule); 4 peacetime grocery → RELEASE; 5 peacetime account takeover → HOLD; 6 red-team smurfing → HOLD.
