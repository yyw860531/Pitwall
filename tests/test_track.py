"""Tests for pitwall/track.py — corner detection and sector parsing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from pitwall.track import (
	corners_from_telemetry,
	_find_corner_regions,
	read_sectors,
)


# ---------------------------------------------------------------------------
# Helpers — generate synthetic telemetry
# ---------------------------------------------------------------------------

def _make_samples(distances, lat_gs):
	"""Build a list of sample dicts from parallel arrays."""
	return [
		{"lap_distance_m": d, "lat_g": g}
		for d, g in zip(distances, lat_gs)
	]


def _straight_then_corner(
	total_m=1000.0, corner_start=400.0, corner_end=600.0, peak_g=1.2, n=200
):
	"""Generate a lap with one clear corner and straight sections."""
	dists = np.linspace(0, total_m, n)
	lat_gs = np.zeros(n)
	for i, d in enumerate(dists):
		if corner_start <= d <= corner_end:
			# Bell curve peaking at midpoint
			mid = (corner_start + corner_end) / 2
			spread = (corner_end - corner_start) / 4
			lat_gs[i] = peak_g * np.exp(-0.5 * ((d - mid) / spread) ** 2)
	return _make_samples(dists.tolist(), lat_gs.tolist())


# ---------------------------------------------------------------------------
# Corner detection from telemetry
# ---------------------------------------------------------------------------

class TestFindCornerRegions:
	def test_single_corner_detected(self):
		samples = _straight_then_corner(peak_g=1.5)
		regions = _find_corner_regions(samples)
		assert len(regions) >= 1
		start, apex, end = regions[0]
		assert 350 < start < 450
		assert 470 < apex < 530
		assert 550 < end < 650

	def test_no_corners_on_straight(self):
		dists = np.linspace(0, 1000, 200)
		lat_gs = np.full(200, 0.1)  # below threshold
		samples = _make_samples(dists.tolist(), lat_gs.tolist())
		regions = _find_corner_regions(samples)
		assert len(regions) == 0

	def test_short_blip_filtered_out(self):
		"""A brief spike < min_length_m should not be detected."""
		dists = np.linspace(0, 1000, 200)
		lat_gs = np.zeros(200)
		# 10m spike — shorter than min_length_m (30m)
		for i, d in enumerate(dists):
			if 500 <= d <= 510:
				lat_gs[i] = 1.0
		samples = _make_samples(dists.tolist(), lat_gs.tolist())
		regions = _find_corner_regions(samples)
		assert len(regions) == 0

	def test_too_few_samples_returns_empty(self):
		samples = _make_samples([0, 100, 200], [0.0, 1.0, 0.0])
		regions = _find_corner_regions(samples)
		assert len(regions) == 0

	def test_null_lat_g_handled(self):
		"""Samples with None lat_g should not crash."""
		dists = np.linspace(0, 500, 50).tolist()
		lat_gs = [None] * 50
		samples = _make_samples(dists, lat_gs)
		regions = _find_corner_regions(samples)
		assert len(regions) == 0


class TestCornersFromTelemetry:
	def test_consistent_corner_across_laps(self):
		"""A corner appearing in all laps should be detected."""
		laps = [_straight_then_corner(peak_g=1.5) for _ in range(5)]
		corners = corners_from_telemetry(laps)
		assert len(corners) >= 1
		c = corners[0]
		assert "name" in c
		assert "start_m" in c
		assert "apex_m" in c
		assert "end_m" in c
		assert c["start_m"] < c["apex_m"] < c["end_m"]

	def test_one_off_corner_filtered_out(self):
		"""A corner appearing in only 1 of 5 laps should be filtered."""
		normal = _straight_then_corner(peak_g=0.2)  # below threshold
		outlier = _straight_then_corner(peak_g=1.5)
		laps = [normal] * 4 + [outlier]
		corners = corners_from_telemetry(laps)
		assert len(corners) == 0

	def test_corner_appears_in_two_of_six_laps_kept(self):
		"""A corner in 2/6 laps must not be dropped by integer threshold rounding.

		Old code: max(1, 6 * 0.4) = 2.4 — cluster of 2 failed (2 < 2.4).
		New code: max(1, int(6 * 0.4)) = 2 — cluster of 2 passes (2 < 2 is False).
		"""
		corner = _straight_then_corner(peak_g=1.5)
		no_corner = _straight_then_corner(peak_g=0.1)  # below threshold
		laps = [corner, corner, no_corner, no_corner, no_corner, no_corner]
		corners = corners_from_telemetry(laps)
		assert len(corners) >= 1

	def test_single_lap_session_detects_corners(self):
		"""Corner detection must work with just one valid lap."""
		laps = [_straight_then_corner(peak_g=1.5)]
		corners = corners_from_telemetry(laps)
		assert len(corners) >= 1

	def test_empty_input(self):
		assert corners_from_telemetry([]) == []

	def test_nearby_corners_merged(self):
		"""Two corners within 20m gap should merge into one."""
		dists = np.linspace(0, 2000, 400)
		lat_gs = np.zeros(400)
		# Corner A: 400-480m, Corner B: 490-570m (gap = 10m < 20m)
		for i, d in enumerate(dists):
			if 400 <= d <= 480:
				lat_gs[i] = 1.0
			elif 490 <= d <= 570:
				lat_gs[i] = 1.0
		samples = _make_samples(dists.tolist(), lat_gs.tolist())
		laps = [samples] * 5
		corners = corners_from_telemetry(laps)
		# Should merge into 1 corner, not 2
		corners_in_range = [c for c in corners if 350 < c["start_m"] < 650]
		assert len(corners_in_range) == 1

	def test_corners_named_sequentially(self):
		"""Corners should be named T1, T2, T3..."""
		# Two well-separated corners
		dists = np.linspace(0, 3000, 600)
		lat_gs = np.zeros(600)
		for i, d in enumerate(dists):
			if 400 <= d <= 550:
				lat_gs[i] = 1.2
			elif 1800 <= d <= 1950:
				lat_gs[i] = 1.2
		samples = _make_samples(dists.tolist(), lat_gs.tolist())
		laps = [samples] * 5
		corners = corners_from_telemetry(laps)
		assert len(corners) >= 2
		assert corners[0]["name"] == "T1"
		assert corners[1]["name"] == "T2"


# ---------------------------------------------------------------------------
# Sector parsing from sections.ini
# ---------------------------------------------------------------------------

class TestReadSectors:
	def test_three_sectors(self, tmp_path):
		ini = tmp_path / "sections.ini"
		ini.write_text(
			"[SECTION_0]\nIN=0.0\nOUT=0.35\n"
			"[SECTION_1]\nIN=0.35\nOUT=0.72\n"
			"[SECTION_2]\nIN=0.72\nOUT=1.0\n"
		)
		boundaries = read_sectors(ini, 5000.0)
		assert len(boundaries) == 2
		assert boundaries[0] == round(0.35 * 5000, 1)
		assert boundaries[1] == round(0.72 * 5000, 1)

	def test_two_sectors(self, tmp_path):
		ini = tmp_path / "sections.ini"
		ini.write_text(
			"[SECTION_0]\nIN=0.0\nOUT=0.55\n"
			"[SECTION_1]\nIN=0.55\nOUT=1.0\n"
		)
		boundaries = read_sectors(ini, 4000.0)
		assert len(boundaries) == 1
		assert boundaries[0] == round(0.55 * 4000, 1)

	def test_missing_file_returns_empty(self):
		boundaries = read_sectors(Path("/nonexistent/sections.ini"), 5000.0)
		assert boundaries == []

	def test_none_path_returns_empty(self):
		boundaries = read_sectors(None, 5000.0)
		assert boundaries == []

	def test_zero_track_length_returns_empty(self, tmp_path):
		ini = tmp_path / "sections.ini"
		ini.write_text("[SECTION_0]\nIN=0.0\nOUT=0.5\n[SECTION_1]\nIN=0.5\nOUT=1.0\n")
		boundaries = read_sectors(ini, 0.0)
		assert boundaries == []

	def test_single_section_returns_empty(self, tmp_path):
		"""Need at least 2 sections to produce a boundary."""
		ini = tmp_path / "sections.ini"
		ini.write_text("[SECTION_0]\nIN=0.0\nOUT=1.0\n")
		boundaries = read_sectors(ini, 5000.0)
		assert boundaries == []
