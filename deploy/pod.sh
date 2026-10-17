#!/usr/bin/env bash
# (Re)create the "nyaya" pod: api (port 8000) + explainer (Granite, localhost:8001 inside the pod).
# Run on the server as linux1 (rootless Podman, SELinux enforcing). Chezhil only (plan §18.7).
#
# Runs IBM's s390x Jupyter image unchanged (Python 3.12, torch + NNPA, xgboost, llama_cpp, Granite gguf). Podman 5.8
# cannot `podman build` or `podman commit` on top of it (its OCI manifest lists docker-typed layers: "unsupported MIME
# type for compression"), so the packages from deploy/requirements.txt that the image lacks go into $DEPS on the host,
# mounted read-only on PYTHONPATH. Code is mounted from ~/shared/nyaya, so `git pull` + `podman pod restart nyaya`
# ships new code.
set -euo pipefail
REPO="${REPO:-$HOME/shared/nyaya}"
DATA="${DATA:-$HOME/shared/data}"
VAR="${VAR:-$HOME/nyaya-var}"          # ledger + AES key, private to the pod (not in ~/shared, not in git)
DEPS="${DEPS:-$HOME/nyaya-pydeps}"     # pip packages missing from the base image
BASE="${BASE:-registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest}"
mkdir -p "$VAR" "$REPO/artifacts"
chmod 700 "$VAR"

if ! cmp -s "$REPO/deploy/requirements.txt" "$DEPS/.requirements.txt"; then
  rm -rf "$DEPS" && mkdir -p "$DEPS"
  # Ask pip what it would add to the image's own venv, then install exactly that (no shadowing of torch & co).
  podman run --rm --user 0 -v "$REPO/deploy/requirements.txt:/req.txt:ro,z" -v "$DEPS:/deps:z" "$BASE" sh -ec '
    /opt/venv/bin/pip install --quiet --dry-run --report /tmp/report.json -r /req.txt
    pkgs=$(/opt/venv/bin/python -c "import json; r=json.load(open(\"/tmp/report.json\")); print(\" \".join(i[\"metadata\"][\"name\"]+\"==\"+i[\"metadata\"][\"version\"] for i in r[\"install\"]))")
    echo "installing into /deps: $pkgs"
    [ -z "$pkgs" ] || /opt/venv/bin/pip install --quiet --no-cache-dir --no-deps --target /deps $pkgs'
  cp "$REPO/deploy/requirements.txt" "$DEPS/.requirements.txt"
fi

podman pod rm -f nyaya 2>/dev/null || true
# keep-id: the image's user (ibm-user, 1000) is linux1 on the host, so it can write $VAR (mode 700).
podman pod create --name nyaya --userns keep-id:uid=1000,gid=1000 -p 8000:8000

# :z = shared SELinux label (the notebook container also uses ~/shared); :Z = private label for the ledger dir.
COMMON=(--pod nyaya --restart unless-stopped -w /opt/nyaya
  -v "$REPO:/opt/nyaya:ro,z" -v "$DATA:/data:ro,z" -v "$DEPS:/opt/pydeps:ro,z"
  -e PYTHONPATH=/opt/nyaya:/opt/pydeps -e PYTHONUNBUFFERED=1 -e PYTHONDONTWRITEBYTECODE=1
  -e NYAYA_ARTIFACTS=/opt/nyaya/artifacts -e NYAYA_ACCOUNTS=/data/accounts_v2.csv.gz)

podman run -d --name nyaya-explainer "${COMMON[@]}" --memory 1500m \
  "$BASE" python -m uvicorn explain.server:app --host 127.0.0.1 --port 8001

podman run -d --name nyaya-api "${COMMON[@]}" --memory 2g -v "$VAR:/var/nyaya:Z" \
  -e NYAYA_LEDGER=/var/nyaya/ledger.jsonl -e NYAYA_LEDGER_KEY_FILE=/var/nyaya/ledger.key \
  -e NYAYA_EXPLAINER_URL=http://127.0.0.1:8001 ${NYAYA_ANALYST_TOKEN:+-e NYAYA_ANALYST_TOKEN="$NYAYA_ANALYST_TOKEN"} \
  "$BASE" python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

sleep 8
podman pod ps
curl -s localhost:8000/health && echo
curl -s localhost:8000/api/v1/system | head -c 600 && echo
