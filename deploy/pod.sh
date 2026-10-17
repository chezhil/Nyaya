#!/usr/bin/env bash
# Build the image and (re)create the "nyaya" pod: api (port 8000) + explainer (Granite, localhost:8001 inside the pod).
# Run on the server as linux1 (rootless Podman, SELinux enforcing). Chezhil only (plan §18.7).
set -euo pipefail
REPO="${REPO:-$HOME/shared/nyaya}"
DATA="${DATA:-$HOME/shared/data}"
VAR="${VAR:-$HOME/nyaya-var}"          # ledger + AES key, private to the pod (not in ~/shared, not in git)
mkdir -p "$VAR" "$REPO/artifacts"
chmod 700 "$VAR"

podman build -t localhost/nyaya:latest -f "$REPO/deploy/Containerfile" "$REPO"

podman pod rm -f nyaya 2>/dev/null || true
podman pod create --name nyaya -p 8000:8000

# :z = shared SELinux label (the notebook container also uses ~/shared); :Z = private label for the ledger dir.
COMMON=(--pod nyaya --restart unless-stopped -v "$REPO:/opt/nyaya:ro,z" -v "$DATA:/data:ro,z")

podman run -d --name nyaya-explainer "${COMMON[@]}" --memory 1500m \
  localhost/nyaya:latest python -m uvicorn explain.server:app --host 127.0.0.1 --port 8001

podman run -d --name nyaya-api "${COMMON[@]}" --memory 2g -v "$VAR:/var/nyaya:Z" \
  -e NYAYA_EXPLAINER_URL=http://127.0.0.1:8001 ${NYAYA_ANALYST_TOKEN:+-e NYAYA_ANALYST_TOKEN="$NYAYA_ANALYST_TOKEN"} \
  localhost/nyaya:latest

sleep 5
podman pod ps
curl -s localhost:8000/health && echo
curl -s localhost:8000/api/v1/system | head -c 600 && echo
