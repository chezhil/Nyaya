# Platform evidence (LinuxONE, 17 Oct 2026)

Collected on the LinuxONE Community Cloud VM by `deploy/evidence.sh` while the `nyaya` pod was running, plus the
load test. Files are unedited command output.

| File | What it shows |
|---|---|
| `lscpu.txt` | s390x, big endian, 3 vCPUs, machine type 9175; CPU features include `nnpa`; `OPENSSL_s390xcap` lists the CPACF instructions OpenSSL uses (kimd, km, kma, …) |
| `selinux.txt`, `podman_info.txt` | SELinux Enforcing on the host; Podman rootless with SELinux enabled |
| `pod_ps.txt`, `podman_stats.txt` | the `nyaya` pod (api + explainer) and per-container memory/CPU at that moment |
| `openssl_sha256.txt`, `openssl_aes256gcm.txt` | `openssl speed -evp`, 3 s per block size. At 16 KB blocks: SHA-256 4.26 GB/s, AES-256-GCM 12.31 GB/s |
| `system.json` | `GET /api/v1/system`: real models `A-xgb-iso-1+B-mlp-1`, Model B on `nnpa`, `engine-1`, accounts v2 |
| `ledger_verify.json` | `GET /api/v1/ledger/verify`: chain valid, 2,374 records, verified in 64.8 ms |
| `loadtest.json` | `deploy/loadtest.py --n 2000 --concurrency 8` against `/api/v1/evaluate` from a container in the same pod (no network hop): 2,000 × HTTP 200, 334.9 req/s, client p50/p95/p99 20.54 / 46.26 / 81.3 ms, server-side 11.68 / 32.95 / 61.36 ms |

`system.json` and `ledger_verify.json` were re-fetched with `127.0.0.1` because `localhost` returned nothing
(fixed in `deploy/evidence.sh`). SELinux shows `unavailable` inside the container; the host value is in `selinux.txt`.
The load test shares the 3 vCPUs with the API, so it is a lower bound for this VM, not a capacity claim.
