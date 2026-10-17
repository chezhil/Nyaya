"""Hook contract tests with synthetic fixtures and a fake scoring bundle.

These results are test expectations only, never model evaluation evidence.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from data.features import MODEL_B_FEATURES
from engine import decide
from sim import pareto, redteam, simulate
from sim.evaluation import _suite_frame, _test_positions


class FakeBundle:
    legacy_threshold = 0.5

    def info(self):
        # Exercise the trained-bundle protocol without loading any model artifacts.
        return {"kind": "real", "model_version": "unit-test-fake"}

    def score_batch(self, a_rows, b_rows):
        return {
            "p_fraud": np.full(len(a_rows), 0.5),
            "p_mule": b_rows["fan_in_15m"].to_numpy(float),
            "p_legacy_raw": np.full(len(a_rows), 0.9),
            "conformal_set": [["legit"] for _ in range(len(a_rows))],
        }


def fixture(variant="base", mule_score=0.0):
    rows = []
    for i, population in enumerate(("normal", "displaced", "syndicate", "syndicate_forward")):
        row = {
            "tx_id": f"fixture-{i}", "population": population, "variant": variant,
            "is_fraud": int(population.startswith("syndicate")),
            "is_mule_recipient": int(population.startswith("syndicate")),
            "amount": 100.0, "type": "PAYMENT", "hour": 12,
            "oldbalanceOrg": 200.0, "newbalanceOrig": 100.0,
            "oldbalanceDest": 0.0, "newbalanceDest": 100.0,
            "geo_shift_km": 0.0, "new_device": 0,
            "merchant_category": "grocery", "in_disaster_zone": 1,
            "severity_tier": 1, "sender_income_band": ("low", "mid", "high", "")[i],
            **{feature: 0.0 for feature in MODEL_B_FEATURES},
        }
        if row["is_mule_recipient"]:
            row["fan_in_15m"] = mule_score
        rows.append(row)
    return pd.DataFrame(rows)


def context():
    return SimpleNamespace(bundle=FakeBundle(), decide=decide, policy={
        "alpha": 0.0, "beta": 10.0, "tau": 1000.0, "tau_review": 0.0,
        "theta_mule": 0.8, "stipend_cap": 10.0,
    })


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name)

    def write(self, tag, df):
        df.to_csv(self.data_dir / f"nyaya_{tag}.csv.gz", index=False)

    def test_independent_suite_uses_whole_eval_and_excludes_forward_rows(self):
        df = fixture()
        self.write("eval", df)
        counts = {"normal": 1, "displaced": 1, "syndicate": 1}
        with patch("sim.evaluation._test_positions", side_effect=AssertionError("no split for eval")):
            sampled, source = _suite_frame({"data_dir": self.temp.name}, counts, seed=7)
            with patch("sim.evaluation.SUITE_COUNTS", counts):
                result = simulate(context(), {"data_dir": self.temp.name})
        self.assertEqual(set(sampled.tx_id), set(df.iloc[:3].tx_id))
        self.assertEqual(source, "independent file eval")
        self.assertEqual(result["suite"]["rows"], sum(counts.values()))
        json.dumps(result, allow_nan=False)

    def test_missing_eval_never_falls_back_to_v2(self):
        self.write("v2", fixture())
        with self.assertRaises(FileNotFoundError):
            _suite_frame({"data_dir": self.temp.name}, {"normal": 1}, seed=7)

    def test_explicit_suite_tag_reads_custom_whole_file(self):
        self.write("custom_eval", fixture())
        sampled, source = _suite_frame(
            {"data_dir": self.temp.name, "suite_tag": "custom_eval"}, {"syndicate": 1}, seed=7)
        self.assertEqual(sampled.population.tolist(), ["syndicate"])
        self.assertEqual(source, "independent file custom_eval")

    def test_pareto_revalues_baselines_for_each_point(self):
        df = pd.concat([fixture()] * 20, ignore_index=True)
        self.write("v2", df)
        params = {"data_dir": self.temp.name, "counts": {"normal": 1, "displaced": 1, "syndicate": 1},
                  "alpha_values": [], "beta_values": [200.0], "tau_values": [],
                  "tau_review_values": [], "theta_mule_values": []}
        with patch("sim.evaluation._test_positions", wraps=_test_positions) as split:
            result = pareto(context(), params)
        split.assert_called_once()
        point = result["points"][0]
        # All baseline actions HOLD. Their cost is (1-p)*beta for each fixture row.
        expected_baseline = sum((1.0 - 0.5) * point["value"] for _ in range(result["suite_rows"]))
        self.assertEqual(point["baselines"]["legacy"]["total_expected_harm_rupees"], expected_baseline)
        self.assertEqual(point["baselines"]["naive_relaxed"]["total_expected_harm_rupees"], expected_baseline)
        self.assertGreater(point["metrics"]["total_expected_harm_rupees"],
                           result["baselines"]["legacy"]["total_expected_harm_rupees"])
        self.assertLess(point["metrics"]["total_expected_harm_rupees"], expected_baseline)
        self.assertEqual(point["loses_to"], [])  # Old fixed-policy comparisons incorrectly flagged both baselines.
        json.dumps(result, allow_nan=False)

    def test_redteam_uses_all_independent_rows_and_eval_base(self):
        self.write("eval", fixture(mule_score=0.9))
        for variant in ("smurf", "device_spoof", "slow_drip"):
            self.write(f"redteam_{variant}", fixture(variant, mule_score=0.0))
        ctx = context()
        ctx.policy["beta"] = 200.0
        with patch("sim.evaluation._test_positions", side_effect=AssertionError("no split for redteam")):
            result = redteam(ctx, {"data_dir": self.temp.name})
        self.assertEqual(result["base"]["rows"], 1)
        self.assertEqual(result["base"]["detection_rate"], 1.0)
        self.assertEqual(result["base"]["strongest_remaining_feature"], "fan_in_15m")
        for item in result["variants"]:
            self.assertEqual(item["rows"], 1)
            self.assertEqual(item["detection_rate"], 0.0)
            self.assertTrue(item["nyaya_weakens"])
            self.assertEqual(item["detection_change_vs_base"], item["detection_rate"] - result["base"]["detection_rate"])
        json.dumps(result, allow_nan=False)

    def test_redteam_rejects_variant_file_without_syndicate(self):
        self.write("eval", fixture())
        self.write("redteam_smurf", fixture("smurf").query("population != 'syndicate'"))
        with self.assertRaisesRegex(ValueError, "no syndicate rows"):
            redteam(context(), {"data_dir": self.temp.name})


if __name__ == "__main__":
    unittest.main()
