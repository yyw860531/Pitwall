"""Tests for pitwall/export.py — corner metrics and trace building."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from pitwall.export import _corner_metrics, _build_corner_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_corner_samples(
	start_m=200.0, end_m=400.0, n=50,
	entry_speed=150.0, min_speed=80.0, exit_speed=130.0,
	brake_start_m=220.0, throttle_start_m=350.0,
):
	"""Generate realistic corner telemetry samples."""
	dists = np.linspace(start_m, end_m, n)
	samples = []
	mid = (start_m + end_m) / 2

	for i, d in enumerate(dists):
		# Speed: V-shape through corner
		if d < mid:
			frac = (d - start_m) / (mid - start_m)
			speed = entry_speed - frac * (entry_speed - min_speed)
		else:
			frac = (d - mid) / (end_m - mid)
			speed = min_speed + frac * (exit_speed - min_speed)

		brake = 80.0 if brake_start_m <= d <= mid else 0.0
		throttle = 60.0 if d >= throttle_start_m else 0.0

		samples.append({
			"lap_distance_m": float(d),
			"speed_kph": float(speed),
			"brake_pct": float(brake),
			"throttle_pct": float(throttle),
			"steering_deg": 0.0,
			"gear": 3,
			"rpm": 5000,
			"lat_g": 0.5,
			"long_g": -0.3 if brake > 0 else 0.2,
		})
	return samples


# ---------------------------------------------------------------------------
# Corner metrics
# ---------------------------------------------------------------------------

class TestCornerMetrics:
	def test_basic_corner_metrics(self):
		corner = {"start_m": 200.0, "end_m": 400.0, "apex_m": 300.0}
		samples = _make_corner_samples()
		m = _corner_metrics(samples, corner)
		assert m is not None
		assert m["brake_point_m"] is not None
		assert 215 < m["brake_point_m"] < 230
		assert 75 < m["min_speed_kph"] < 85
		assert m["throttle_pickup_m"] is not None
		assert 345 < m["throttle_pickup_m"] < 360

	def test_no_braking_corner(self):
		"""Flat-out corner — no brake application."""
		corner = {"start_m": 200.0, "end_m": 400.0, "apex_m": 300.0}
		samples = _make_corner_samples(min_speed=140.0)
		# Override: no braking
		for s in samples:
			s["brake_pct"] = 0.0
		m = _corner_metrics(samples, corner)
		assert m is not None
		assert m["brake_point_m"] is None

	def test_too_few_samples_returns_none(self):
		corner = {"start_m": 200.0, "end_m": 400.0, "apex_m": 300.0}
		samples = _make_corner_samples(n=3)
		m = _corner_metrics(samples, corner)
		assert m is None


class TestBuildCornerSummary:
	def test_summary_has_deltas(self):
		corner = {
			"name": "T1", "display": "T1",
			"start_m": 200.0, "apex_m": 300.0, "end_m": 400.0,
		}
		best = _make_corner_samples(min_speed=85.0, brake_start_m=225.0)
		ref = _make_corner_samples(min_speed=80.0, brake_start_m=220.0)
		summary = _build_corner_summary(best, ref, [corner])
		assert len(summary) == 1
		s = summary[0]
		assert s["corner_name"] == "T1"
		assert "delta" in s
		assert "estimated_time_loss_ms" in s["delta"]
		assert s["priority"] == 1

	def test_empty_corners_returns_empty(self):
		best = _make_corner_samples()
		ref = _make_corner_samples()
		summary = _build_corner_summary(best, ref, [])
		assert summary == []
