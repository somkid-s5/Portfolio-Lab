import tempfile
import unittest
from pathlib import Path

from scripts.run_load import (
    MAX_EXPERIMENT_REQUESTS,
    MAX_PROFILE_REQUESTS,
    MAX_WORKERS,
    build_targets,
    reserve_profile,
    validate_bounds,
)


class LoadBoundsTests(unittest.TestCase):
    def test_profile_and_worker_limits_are_enforced(self):
        validate_bounds(1, 1)
        validate_bounds(MAX_PROFILE_REQUESTS, MAX_WORKERS)
        with self.assertRaises(ValueError):
            validate_bounds(MAX_PROFILE_REQUESTS + 1, 1)
        with self.assertRaises(ValueError):
            validate_bounds(1, MAX_WORKERS + 1)

    def test_seed_produces_repeatable_hot_set_distribution(self):
        first = build_targets(500, 41)
        second = build_targets(500, 41)
        self.assertEqual(first, second)
        hot_details = sum(1 for target in first if target.startswith("/api/products/"))
        self.assertGreaterEqual(hot_details, 350)
        self.assertLessEqual(len(first), MAX_PROFILE_REQUESTS)
        self.assertEqual(MAX_EXPERIMENT_REQUESTS, 2500)

    def test_experiment_reservation_enforces_five_profile_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            out_dir = Path(directory)
            for profile in ("bypass", "cold", "warm", "redis-failure", "change-request"):
                reserve_profile(out_dir, profile, 500)
            with self.assertRaises(ValueError):
                reserve_profile(out_dir, "bypass", 1)
            manifest = (out_dir / "experiment.json").read_text(encoding="utf-8")
            self.assertIn('"attempted_requests": 2500', manifest)
            with self.assertRaises(ValueError):
                reserve_profile(out_dir, "extra", 1)


if __name__ == "__main__":
    unittest.main()
