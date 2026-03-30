"""Tests for pitwall/ingest.py — sector time computation and lap validity."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import numpy as np

try:
	from pitwall.ingest import compute_sector_times
	HAS_INGEST = True
except ImportError:
	HAS_INGEST = False

pytestmark = pytest.mark.skipif(not HAS_INGEST, reason="ldparser not installed")


# ---------------------------------------------------------------------------
# Sector time computation
# ---------------------------------------------------------------------------

class TestComputeSectorTimes:
	def _make_arrays(self, n=100, track_m=5000.0, lap_time_s=120.0):
		"""Generate smooth distance and time arrays for a full lap."""
		dist = np.linspace(0, track_m, n)
		time = np.linspace(0, lap_time_s, n)
		mask = np.ones(n, dtype=bool)
		return dist, time, mask

	def test_two_sectors(self):
		dist, time, mask = self._make_arrays(track_m=5000.0, lap_time_s=120.0)
		boundaries = [2500.0]  # midpoint
		result = compute_sector_times(dist, time, mask, boundaries)
		assert len(result) == 2
		assert result[0] is not None
		assert result[1] is not None
		# Should sum to roughly the total lap time (in ms)
		total = sum(result)
		assert abs(total - 120000) < 2000  # within 2s tolerance from interpolation

	def test_three_sectors(self):
		dist, time, mask = self._make_arrays(track_m=6000.0, lap_time_s=90.0)
		boundaries = [2000.0, 4000.0]
		result = compute_sector_times(dist, time, mask, boundaries)
		assert len(result) == 3
		assert all(s is not None for s in result)
		# Each sector should be roughly 30s (30000ms)
		for s in result:
			assert 25000 < s < 35000

	def test_boundary_not_crossed(self):
		"""Lap shorter than boundary should return all None."""
		dist, time, mask = self._make_arrays(track_m=1000.0)
		boundaries = [2000.0]  # beyond lap distance
		result = compute_sector_times(dist, time, mask, boundaries)
		assert all(s is None for s in result)

	def test_empty_boundaries(self):
		dist, time, mask = self._make_arrays()
		result = compute_sector_times(dist, time, mask, [])
		# No boundaries = 1 sector = full lap time
		assert len(result) == 1
		assert result[0] is not None

	def test_sector_times_are_positive(self):
		dist, time, mask = self._make_arrays(track_m=4000.0, lap_time_s=80.0)
		boundaries = [1000.0, 2500.0]
		result = compute_sector_times(dist, time, mask, boundaries)
		for s in result:
			if s is not None:
				assert s > 0
