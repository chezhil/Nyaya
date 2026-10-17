# NYAYA model card

All figures below were produced on the IBM LinuxONE server (s390x, big-endian) on 17 Oct 2026 and are copied from
the saved run outputs named in each section (`artifacts/` on the server, git-ignored). Nothing is hand-set.
Data is synthetic (`data/generate.py`, v2) and the results describe the method on that data, not real-world accuracy.

| Item | Value |
|---|---|
| Model A | `A-xgb-iso-1`: XGBoost (binary:logistic) + isotonic calibration + split conformal (α = 0.1) |
| Model B | `B-mlp-1`: PyTorch MLP 7→32→16→1, trained on CPU, served on the Telum NNPA |
| Engine | `engine-1`: expected-harm policy (`engine/policy.py`), values in `api/policy_defaults.json` |
| Training data | `nyaya_v2` (94,012 payments, seed 7), stratified random splits by population × label |
| Evaluation data | `nyaya_eval` (94,113 payments, **seed 101**, never used for training, calibration or tuning); 10,000-payment suite = 7,500 normal / 1,800 displaced / 700 syndicate |
| Code | branch `kaustub-ml`; reproduce with the commands at the end |

## Intended use

Scoring payments during declared disasters so a bank can choose RELEASE, REVIEW (stipend now, escrow the rest for
48 h, auto-release unless fraud is confirmed) or HOLD. A decision aid beside an existing fraud engine, with an analyst
queue and one-tap appeal. Not for use on real customers without retraining on real data, and not as the only control.

Income band is never a model input; it is used only to audit decisions afterwards.

## Model A: payment fraud (`metrics_a.json`, v2 test split, 9,408 rows)

| Metric | Value |
|---|---|
| PR-AUC | 0.985 |
| ROC-AUC | 0.998 |
| Brier score, raw → calibrated | 0.01090 → 0.01102 (isotonic calibration did **not** improve Brier on this split; reliability tables are in notebook 02) |
| Conformal coverage (target 0.90) | 0.902, qhat 0.0099 |
| Conformal sets | 9.7% empty, 0% "both". With two labels a set can hold both only when qhat ≥ 0.5, so an accurate model's uncertain cases come out **empty**; the engine treats empty and both alike as uncertain → REVIEW |

On the independent 10k suite (`sim/simulate.json`): PR-AUC 0.977, conformal coverage 0.920.

## Model B: mule-ring payee (`metrics_b.json`, v2 test split, 14,102 rows)

| Metric | Value |
|---|---|
| PR-AUC | 0.987 (v1 data gave 1.000 because every feature separated perfectly; v2 adds realistic overlap) |
| ROC-AUC | 0.997 |
| Brier | 0.00918 |
| Flag rate at P(mule) ≥ 0.8 | syndicate 84.1%, mule→cash-out forwards 99.3%, legitimate community-collector donations **13.9%**, displaced 0.04%, normal 0.03% |
| NNPA vs CPU outputs | same PR-AUC (0.987); max absolute probability difference 0.0071 on test rows |

On the independent suite: PR-AUC 0.974.

## Decision policy (a choice, not a free win)

`tau = 250`, `tau_review = 0`, `theta_mule = 0.8`, `alpha = 0.6`, `beta = Rs 345`, `stipend_cap = Rs 3,000`,
`zone_hold_needs_mule = true`. Chosen from `engine_tune.json` (v2 test split); reasons in `api/policy_defaults.json`.
β and the cap are the official figures cited in `docs/policy.md` clause 5; verify them before the video.

**The zone rule.** With `zone_hold_needs_mule` on, a payment inside a declared disaster zone can be fully frozen only
by the mule override; any other HOLD becomes a REVIEW, which releases the stipend. That is what makes "victims left
with Rs 0" near zero by design. The price is that fraud which spoofs the zone and is not mule-flagged gets the stipend.
Measured on every account takeover in the independent file (`ato_zone_rule_audit`, 900 takeovers, Rs 2.68 crore,
98 of them spoofing the zone):

| Zone rule | ATO HOLD | ATO REVIEW | ATO RELEASE | ATO leakage | Spoofed-zone ATO HOLD | Spoofed-zone leakage |
|---|---|---|---|---|---|---|
| off | 88.8% | 1.8% | 9.4% | Rs 2.52 lakh | 69.4% | Rs 0.99 lakh |
| on | 81.2% | 7.7% | 11.1% | Rs 4.28 lakh | **0%** | Rs 2.75 lakh |

So the rule costs about Rs 1.76 lakh more takeover leakage on this file (+70%), all of it from takeovers that spoof
the zone, which can no longer be frozen. On the tuning split it also lowers syndicate HOLDs from 97.5% to 82.2% (the
rest go to REVIEW with escrow). Set it to `false` to restore the plan's table as written.

## Headline results (independent 10k suite, `sim/simulate.json`)

| | Legacy | Naive relaxed | NYAYA |
|---|---|---|---|
| Victims left with Rs 0 | 22.5% (405 of 1,800) | 9.7% (175) | **0.06% (1, mule-flagged)** |
| Share of victims' money available immediately | 54.6% | 57.6% | 85.5% |
| Fraud leakage | Rs 75.5 lakh | Rs 76.4 lakh | Rs 2.43 lakh |
| Total expected harm (engine's harm terms) | Rs 98.1 lakh | Rs 88.9 lakh | Rs 8.2 lakh |

**Legacy** = the same Model A with the disaster context set to zero, HOLD above its 1% false-positive threshold on
peacetime validation payments (0.0354). **Naive relaxed** = legacy with HOLDs waived in zones up to the stipend cap.

How to quote this:
- The legacy baseline catches 35.4% of syndicate payments in the suite, because the context-zeroed model learned the
  syndicate pattern partly through the zone features. A legacy engine trained without those features from the start
  could catch more, so **quote the fraud-leakage gap only with that definition attached**, or not at all. The
  victims-left-with-Rs-0 gap is the robust headline.
- An earlier run reported legacy catching 0% of syndicate payments. That was an artefact: the threshold was taken
  over all validation negatives, where context-blind scores of displaced victims inflated it to 0.34. Fixed in
  `models/train_a.py` (peacetime negatives only); `legacy_diagnostics` in `simulate.json` shows the score ranges.
- NYAYA wins on expected harm at every point of the one-at-a-time Pareto sweep (`sim/pareto.json`, 7,450 rows of
  the v2 test split, α, β, τ, τ_review, θ_mule each ±50%); no point loses to a baseline. That harm measure uses the
  engine's own harm terms, so it is not independent evidence.

## Fairness (target: max/min ratio ≤ 1.25 across synthetic income bands) — **not met**

| View | Freeze ratio | REVIEW ratio |
|---|---|---|
| All payments | 1.48 | 1.35 |
| Legitimate payments only (false-positive parity) | 1.30 | 1.61 |

Legitimate-only counts (frozen / reviewed of n): low 24 / 91 of 4,605; mid 24 / 88 of 3,532; high 7 / 18 of 1,163.
The rates are small (0.5–0.7% frozen) and the high band has few events, so the ratios are noisy, but they are reported
as measured. We did not tune the policy to pass this target.

## Red team: we attacked our own system (`sim/redteam.json`)

Detection = HOLD or REVIEW, over all 6,000 syndicate payments of each file.

| Syndicate | Detected | HOLD | REVIEW | Feature that still carries the most signal |
|---|---|---|---|---|
| Base | 93.8% | 85.0% | 8.9% | forward-within-10-min ratio |
| Smurfing (3× more mules) | 80.4% | 52.8% | 27.6% | forward-within-10-min ratio |
| Device spoofing | 83.5% | 61.1% | 22.5% | forward-within-10-min ratio |
| Slow drip (forward after 12–40 min) | 77.0% | 45.6% | 31.5% | fan-in in 15 min |

NYAYA weakens against every variant; slow drip is the hardest. More of each attack lands in REVIEW, where only the
stipend leaks and the rest waits in escrow for an analyst.

## Telum NNPA (`bench/throughput.json`, Model B, median incl. host↔device transfer, 3 CPU threads)

| Batch | CPU p50 | NNPA p50 |
|---|---|---|
| 1 | 0.026 ms | 0.035 ms |
| 100 | 0.043 ms | 0.040 ms |
| 10,000 | 1.70 ms | 4.16 ms |

**Model B runs on the NNPA, and is measured slower than the CPU at this model size** (transfer overhead outweighs the
compute for a 7→32→16→1 network). No speed-up is claimed (AGENTS.md rule 8).

## Limitations

- Synthetic data: population behaviour, overlaps and red-team variants are designed by us; real fraud differs.
- The legacy baseline is one construction (context zeroed); other baselines would score differently.
- The zone rule trades takeover leakage for victim protection (above); a bank may choose differently.
- Fairness target not met; Model B falsely flags 13.9% of legitimate donations to community collectors.
- Isotonic calibration did not improve Brier on the test split.

## Reproduce (inside the `notebook` container on the server)

```bash
python -m data.generate --tag v2                       # training data (seed 7)
python -m data.generate --tag eval --seed 101          # independent evaluation data
for v in smurf device_spoof slow_drip; do python -m data.generate --tag redteam_$v --variant $v; done
python -m models.train_a --out ~/shared/nyaya/artifacts
python -m models.train_b --out ~/shared/nyaya/artifacts
python -m engine.tune
python -m sim.run simulate --out ~/shared/nyaya/artifacts/sim/simulate.json
python -m sim.run pareto --params '{"counts": {"normal": 5500, "displaced": 1400, "syndicate": 550}}' --out ~/shared/nyaya/artifacts/sim/pareto.json
python -m sim.run redteam --out ~/shared/nyaya/artifacts/sim/redteam.json
python deploy/bench_throughput.py --artifacts ~/shared/nyaya/artifacts
```
Then execute `notebooks/01`–`05`.
