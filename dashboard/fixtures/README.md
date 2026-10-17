# Recorded responses (offline mode)

The dashboard shows these only when the API is unreachable, and labels them "recorded on LinuxONE".
They are unmodified responses from the `nyaya` pod on the LinuxONE server (17 Oct 2026, models
`A-xgb-iso-1+B-mlp-1`, `engine-1`, policy from `api/policy_defaults.json`):

| File | Source |
|---|---|
| `system.json`, `policy.json`, `scenarios.json`, `queue.json` | `GET /api/v1/system`, `/policy`, `/scenarios`, `/queue` |
| `scenario_1.json` … `scenario_6.json` | `POST /api/v1/scenarios/{n}/run` |
| `replay.json` | `POST /api/v1/replay` (defaults: 50 per hour, seed 11, base) |
| `simulate.json`, `pareto.json`, `redteam.json` | `POST /api/v1/simulate`, `GET /api/v1/pareto`, `GET /api/v1/redteam` (saved `artifacts/sim/*.json`) |
| `throughput.json` | `artifacts/bench/throughput.json` (`deploy/bench_throughput.py`; the API has no endpoint for it) |

`queue.json` is empty: the API restarted after the scenario runs and the queue lives in memory.
`system.json` was taken from a fresh process, so it has no latency stats yet; docs/ was not merged then
(`policy_source: fixture`). To re-record, call the same endpoints on the server and copy the bodies here.
