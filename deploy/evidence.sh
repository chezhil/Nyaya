#!/usr/bin/env bash
# Collect platform evidence (plan §16) into docs/evidence/ on the server. Review before committing.
set -uo pipefail
OUT="${1:-$HOME/shared/nyaya/docs/evidence}"
mkdir -p "$OUT"
{ lscpu; echo; grep -m1 features /proc/cpuinfo; } > "$OUT/lscpu.txt"
getenforce > "$OUT/selinux.txt" 2>&1
podman info --format '{{.Host.Security.Rootless}} rootless={{.Host.Security.Rootless}} selinux={{.Host.Security.SELinuxEnabled}}' > "$OUT/podman_info.txt" 2>&1
podman pod ps > "$OUT/pod_ps.txt" 2>&1
podman stats --no-stream > "$OUT/podman_stats.txt" 2>&1
openssl speed -elapsed -seconds 3 -evp aes-256-gcm > "$OUT/openssl_aes256gcm.txt" 2>&1
openssl speed -elapsed -seconds 3 -evp sha256 > "$OUT/openssl_sha256.txt" 2>&1
curl -s http://127.0.0.1:8000/api/v1/system > "$OUT/system.json"
curl -s http://127.0.0.1:8000/api/v1/ledger/verify > "$OUT/ledger_verify.json"
ls -la "$OUT"
