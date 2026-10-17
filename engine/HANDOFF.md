# Kaustub's handoff: models/, engine/ (ML and decision engine)

Branch `kaustub-ml`. Written 17 Oct 2026 so Chezhil can continue this work. Nothing here is merged to `main` yet.

## What is done and pushed
| Area | Files | State |
|---|---|---|
| Model A training | `models/train_a.py`, `models/common.py` | XGBoost, isotonic calibration, split conformal. Writes all CONTRACTS.md section 2 Model A artifacts plus `metrics_a.json`. |
| Model B training | `models/train_b.py` | PyTorch MLP 7-32-16-1 trained on CPU, checks NNPA vs CPU outputs. Writes `model_b.pt`, `model_b_meta.json`, `metrics_b.json`. |
| Engine | `engine/policy.py`, `engine/counterfactual.py`, `engine/__init__.py` | `decide`, `counterfactual`, `ENGINE_VERSION = "engine-1"`. 14 unit tests in `engine/tests/`. |
| Sensitivity run | `engine/tune.py` | Grid over `tau` x `tau_review` on the held-out Model A test split. Writes `<artifacts>/engine_tune.json`. |
| Sim (Codex) | `sim/` | `simulate`, `pareto`, `redteam`, CLI `python -m sim.run`. Final runs not done. |
| Notebooks (Antigravity) | `notebooks/01-03` | Written, not executed. Still read `nyaya_v1`. |

Latest commit when this was written: `6dd7a34`.

## What is NOT done (in order)
1. **Retrain on v2 and read the results.** A detached job was started on the server (log `~/v2run.log`: engine tests, `train_a`, `train_b`, `engine.tune`, all on tag `v2`). I never managed to read the log: SSH dropped while it ran. Read it first. If it is empty or failed, rerun the commands below. **No v1 or v2 numbers from this file should be trusted until you see the log yourself.**
2. **Choose `tau` and `tau_review`** from `engine_tune.json`, then set them (and `alpha`, `theta_mule`) in `api/policy_defaults.json` (Chezhil's folder, so he edits it). Record the choice and the reason in `api/policy_defaults.json` `sources`.
3. **Open the PR `kaustub-ml` into `main`** with the v2 metrics in the description.
4. **Tell Codex** when tuned values are set, so it can run the final 10k suite. Codex also reports that the generator output is too small for a full unique held-out suite: it needs at least 75,000 normal, 18,000 displaced and 7,000 syndicate rows in the base data (v2 has 94,012 payments in total). Red-team datasets (`--variant smurf|device_spoof|slow_drip`) must be generated on the server.
5. **Tell Antigravity** to switch notebooks 01-03 to tag `v2`, then build 04 (reads `engine_tune.json`) and 05 (reads Codex's results).
6. Remaining plan items for the ML lead: Model B NNPA vs CPU timing and batch throughput (notebook 03 and `deploy/bench_throughput.py`), model card numbers, check every number on the slides.

## How to run (always on the server, inside the `notebook` container)
The server worktree is `~/shared/nyaya-kaustub` (separate from `~/shared/nyaya`, so the API checkout is not disturbed). Update it with:
```bash
cd ~/shared/nyaya-kaustub && git fetch -q origin && git checkout -q --detach origin/kaustub-ml
```
Then, in one detached job (run only one heavy job at a time, and use `nice -n 19`):
```bash
podman exec -w /home/ibm-user/shared/nyaya-kaustub \
  -e PYTHONPATH=/home/ibm-user/shared/nyaya-kaustub \
  -e NYAYA_DATA=/home/ibm-user/shared/data \
  notebook sh -c "python -m pytest engine -q -p no:cacheprovider \
  && python -m models.train_a --out /home/ibm-user/shared/nyaya/artifacts \
  && python -m models.train_b --out /home/ibm-user/shared/nyaya/artifacts \
  && NYAYA_ARTIFACTS=/home/ibm-user/shared/nyaya/artifacts python -m engine.tune"
```
Default data tag is `v2`; pass `--tag v1` to use the old data. Artifacts go to `~/shared/nyaya/artifacts/` (git-ignored): `model_a.json`, `model_a_meta.json`, `calibration.json`, `conformal.json`, `model_b.pt`, `model_b_meta.json`, plus `metrics_a.json`, `metrics_b.json`, `engine_tune.json`. Everything is seeded (`SEED = 7`), so reruns reproduce.

Root `pytest.ini` only lists `data api ledger explain` in `testpaths`. Add `engine models sim` there (root file, Chezhil's) or run `pytest engine` explicitly.

## Decisions and why
- **Splits are random, stratified by `population|is_fraud`** (Model A: 60/10/10/10/10 train/val/isotonic/conformal/test), not by time. A time split would put the whole cyclone event in the later splits and train on no disaster rows.
- **Legacy threshold** = 99th percentile of the context-zeroed model's score on validation negatives (1% FPR), stored as `legacy_threshold` in `model_a_meta.json`.
- **Conformal**: score = 1 - p(true label). Empty and "both" sets are both treated as uncertain by the engine (`!= 1`), per Chezhil's note, because an accurate model never produces "both" at alpha 0.1.
- **`tau_review`** is an addition to the plan's table. The plan has one `tau`: HOLD if delta >= tau and REVIEW if |delta| < tau. With `tau` = 5000 on v1 data, every payment over the stipend cap (Rs 3,000) went to REVIEW, because delta for a legitimate payment is only -h_hold (a few hundred rupees). Splitting it lets the HOLD threshold and the REVIEW band move separately. `tau_review` defaults to `tau`, which reproduces the plan exactly.
- **Counterfactuals** edit the payment (amount, new_device, geo_shift_km, hour, severity) and rebuild the Model A row with `data.features.tx_features`, so the edited row stays consistent. They only use the live scoring function.

## Findings so far (v1 data, before the v2 retrain; recheck on v2)
- Model B scored PR-AUC 1.0000 (flag rate 1.0 on syndicate rows, 0.0 elsewhere): the v1 data was too easy. Chezhil's v2 was built to fix this. Not yet rechecked on v2.
- On v1 the legacy baseline flagged only 0.5% of displaced payments (0.8% of normal), so a "victims left with Rs 0" headline would have shown no gap. Chezhil reports v2 gives about 21% vs about 1% on a proxy. Not yet checked with our models.
- With the plan's default `tau` = 5000 on v1: essentially all payments over Rs 3,000 went to REVIEW (22.2% of normal payments), and 18.7% of account-takeover payments were released in full because small amounts cannot reach a Rs 5,000 HOLD threshold. This is why `tau` needs tuning.
- NNPA vs CPU max abs output difference on Model B was about 0.00029 on v1 test rows. NNPA speed-up has not been measured; do not claim acceleration until it is.

## Practical warnings
- **SSH drops while a heavy job is running** (3 vCPUs, XGBoost uses `nthread=3`). Symptoms: "Timeout, server 148.100.109.13 not responding", hangs, "Connection reset". The server itself stayed up. Use `ssh -n`, start jobs detached (`setsid nohup ... < /dev/null &`), log to a file, and read the log with retries. `nice -n 19` on the job should help.
- Use `import torch` only, never `import torch_nnpa`.
- Never edit tracked files directly on the server. Edit on a laptop, push, then update the server worktree as above.
- Allowed libraries only: xgboost, scikit-learn, torch, numpy, pandas, networkx, rank-bm25, llama_cpp, fastapi, uvicorn, pycryptodome. No lightgbm, onnxruntime or shap.
- Local Windows machine has no Python, so tests only run on the server.
