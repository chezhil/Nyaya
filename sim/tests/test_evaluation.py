from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from sim.evaluation import _fairness, _fixed_sample, _ratio


def _frame(n: int = 500) -> pd.DataFrame:
    populations = np.resize(np.array(["normal", "displaced", "syndicate"]), n)
    return pd.DataFrame({
        "population": populations,
        "is_fraud": (populations == "syndicate").astype(int),
        "sender_income_band": np.resize(np.array(["low", "mid", "high", ""]), n),
    })


class EvaluationTests(unittest.TestCase):
    def test_fixed_sample_is_deterministic_unique_and_held_out(self):
        df = _frame()
        counts = {"normal": 10, "displaced": 8, "syndicate": 6}
        a = _fixed_sample(df, counts, seed=7)
        b = _fixed_sample(df, counts, seed=7)
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(len(a), sum(counts.values()))
        self.assertTrue(a.index.is_unique)
        self.assertEqual(a["population"].value_counts().to_dict(), counts)

    def test_fixed_sample_refuses_oversampling(self):
        with self.assertRaisesRegex(ValueError, "unique rows are required"):
            _fixed_sample(_frame(90), {"syndicate": 100}, seed=7)

    def test_fairness_reports_rates_without_using_band_as_a_score_input(self):
        df = pd.DataFrame({"sender_income_band": ["low", "low", "mid", "mid", "high", "high"]})
        decisions = pd.DataFrame({"decision": ["HOLD", "REVIEW", "HOLD", "RELEASE", "HOLD", "REVIEW"]})
        result = _fairness(df, decisions)
        self.assertEqual(result["max_min_freeze_ratio"], 1.0)
        self.assertEqual(result["by_sender_income_band"]["mid"]["review_rate"], 0.0)

    def test_ratio_zero_denominator_is_explicitly_unbounded(self):
        self.assertIsNone(_ratio([0.0, 0.2]))


if __name__ == "__main__":
    unittest.main()
