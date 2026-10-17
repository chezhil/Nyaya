"""CLI for server-side evaluation inside the ``notebook`` container."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from api.bundle import load_bundle
from engine import decide
from sim import pareto, redteam, simulate
from sim.evaluation import write_result

POLICY_PATH = Path(__file__).resolve().parents[1] / "api" / "policy_defaults.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("simulate", "pareto", "redteam"))
    parser.add_argument("--params", default="{}", help="JSON object passed to the hook")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    params = json.loads(args.params)
    if not isinstance(params, dict):
        raise ValueError("--params must decode to a JSON object")
    policy = json.loads(POLICY_PATH.read_text())
    bundle = load_bundle()
    if bundle.info().get("kind") != "real":
        reason = getattr(bundle, "fallback_reason", "missing artifacts")
        raise RuntimeError(
            f"Evaluation command '{args.command}' requires trained Model A and Model B artifacts; "
            f"found StubBundle ({reason}). Train models first via models.train_a and models.train_b."
        )
    ctx = SimpleNamespace(bundle=bundle, decide=decide, policy=policy)
    result = {"simulate": simulate, "pareto": pareto, "redteam": redteam}[args.command](ctx, params)
    if args.out:
        write_result(args.out, result)
        print(f"wrote {args.out}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
