"""
orchestrator.py -- orchestrator agent for PitWall session analysis.

The orchestrator is a PLANNER, not an executor. It:
  1. Receives pre-gathered session data (Python, guaranteed first)
  2. Reasons about which corners need which analyses (Claude, zero tools)
  3. Returns a structured dispatch plan

Python handles all execution: sub-agents run in parallel via ThreadPoolExecutor,
and the coaching writer always runs last.

Separation of concerns:
  - Orchestrator agent: decides WHAT to analyse (planner)
  - Python dispatcher: handles HOW to execute (parallel, error handling)
  - Sub-agents: do the actual analysis (each with their own MCP tools)
  - Coaching writer: assembles final report (unconditional, always last)

Usage:
    from pitwall.orchestrator import orchestrate
    coaching_report = orchestrate(session_id, corner_summary)
"""
from __future__ import annotations

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
from config import config  # noqa: E402
from pitwall.agents._base import run_agent, load_prompt  # noqa: E402
from pitwall.agents import (  # noqa: E402
	data_gatherer,
	corner_analysis,
	braking_efficiency,
	balance_diagnosis,
	synthetic_lap,
	coaching_writer,
)

log = logging.getLogger(__name__)
_SYSTEM = load_prompt("orchestrator.txt")

# Max concurrent sub-agent calls (bounded by API rate limits)
_MAX_WORKERS = 6

# Valid analysis types the planner can request
_VALID_ANALYSES = {"corner", "braking", "balance"}


# ---------------------------------------------------------------------------
# Phase 1: Build summary for the planner (no raw traces)
# ---------------------------------------------------------------------------

def _build_summary(payload: dict, corner_summary: list[dict]) -> dict:
	"""Build a lightweight summary for the orchestrator agent."""
	time_loss_map = {
		c["corner_name"]: c.get("delta", {}).get("estimated_time_loss_ms", 0)
		for c in (corner_summary or [])
	}
	corners = []
	for cp in payload["corner_payloads"]:
		corners.append({
			"corner_name":            cp["corner_name"],
			"estimated_time_loss_ms": time_loss_map.get(cp["corner_name"], 0),
			"needs_braking":          cp.get("needs_braking", False),
			"needs_balance":          cp.get("needs_balance", False),
		})
	corners.sort(key=lambda c: c["estimated_time_loss_ms"], reverse=True)

	return {
		"session_meta": {
			"car":                 payload["session_meta"].get("car"),
			"track":               payload["session_meta"].get("track"),
			"fastest_time_ms":     payload["session_meta"].get("fastest_time_ms"),
			"valid_lap_count":     payload["session_meta"].get("valid_lap_count"),
			"theoretical_best_ms": payload["session_meta"].get("theoretical_best_ms"),
		},
		"ref_type":    payload["ref_type"],
		"car_context": payload.get("car_context"),
		"corners":     corners,
	}


# ---------------------------------------------------------------------------
# Phase 2: Plan (orchestrator agent — zero tools, single turn)
# ---------------------------------------------------------------------------

def _plan(summary: dict) -> dict:
	"""
	Run the orchestrator agent to produce a dispatch plan.
	Single-turn, no tools — Claude receives the summary and returns JSON.
	"""
	plan = run_agent(
		system=_SYSTEM,
		user_message=json.dumps(summary, separators=(",", ":")),
		allowed_tools=None,  # zero tools
		max_tokens=2048,
		model=config.claude_model_fast,  # rules-based planning, Haiku is sufficient
		max_turns=2,  # 1 turn + 1 JSON retry buffer
	)
	return plan


# ---------------------------------------------------------------------------
# Phase 3: Dispatch (Python — parallel sub-agents + coaching writer)
# ---------------------------------------------------------------------------

def _dispatch(plan: dict, payload: dict) -> dict:
	"""
	Execute the dispatch plan: run sub-agents in parallel, then coaching writer.
	"""
	corner_payloads_by_name = {
		cp["corner_name"]: cp for cp in payload["corner_payloads"]
	}
	car_context = payload.get("car_context")

	corner_analyses: dict[str, dict] = {}
	braking_results: dict[str, dict] = {}
	balance_results: dict[str, dict] = {}
	synth_result = None

	# Count what we're dispatching
	priority = plan.get("priority_corners", [])
	n_corner = sum(1 for e in priority if "corner" in e.get("analyses", []))
	n_braking = sum(1 for e in priority if "braking" in e.get("analyses", []))
	n_balance = sum(1 for e in priority if "balance" in e.get("analyses", []))
	n_synth = 1 if plan.get("run_synthetic_lap") else 0
	total = n_corner + n_braking + n_balance + n_synth

	log.info(
		"Dispatching %d agent calls (%d corner, %d braking, %d balance, %d synthetic)...",
		total, n_corner, n_braking, n_balance, n_synth,
	)

	futures: dict = {}
	with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
		for entry in priority:
			cname = entry["corner_name"]
			cp = corner_payloads_by_name.get(cname)
			if not cp:
				log.warning("Plan references unknown corner: %s — skipping", cname)
				continue

			analyses = set(entry.get("analyses", ["corner"])) & _VALID_ANALYSES

			if "corner" in analyses:
				fut = pool.submit(corner_analysis.analyze, cp, car_context)
				futures[fut] = ("corner", cname)

			if "braking" in analyses:
				fut = pool.submit(braking_efficiency.analyze, cp, car_context)
				futures[fut] = ("braking", cname)

			if "balance" in analyses:
				fut = pool.submit(balance_diagnosis.analyze, cp, car_context)
				futures[fut] = ("balance", cname)

		if plan.get("run_synthetic_lap"):
			fut = pool.submit(
				synthetic_lap.build,
				payload.get("car_data"),
				payload.get("track_data"),
			)
			futures[fut] = ("synthetic", None)

		# Collect results
		for fut in as_completed(futures):
			kind, cname = futures[fut]
			try:
				result = fut.result()
			except Exception as e:
				log.error("  %s(%s) failed: %s", kind, cname, e)
				continue
			if result is None:
				continue
			if kind == "corner":
				corner_analyses[cname] = result
			elif kind == "braking":
				braking_results[cname] = result
			elif kind == "balance":
				balance_results[cname] = result
			elif kind == "synthetic":
				synth_result = result

	if not corner_analyses:
		log.warning("No corner analyses completed")
	if not braking_results:
		log.info("  No braking analysis triggered")
	if not balance_results:
		log.info("  No balance anomaly detected")

	# Apply synthetic lap metadata
	session_meta = payload["session_meta"]
	session_meta["reference_type"] = payload["ref_type"]
	if synth_result:
		session_meta["reference_type"] = "synthetic"
		session_meta["reference_note"] = (
			f"No reference lap available. Using synthetic baseline "
			f"({synth_result.get('lap_time_ms')} ms, "
			f"confidence: {synth_result.get('confidence', 'unknown')})."
		)

	# Coaching writer always runs last — unconditional
	log.info("Generating coaching report...")
	return coaching_writer.write(
		session_meta=session_meta,
		corner_analyses=list(corner_analyses.values()),
		braking_results=list(braking_results.values()),
		balance_results=list(balance_results.values()),
		car_context=car_context,
	)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def orchestrate(
	session_id: str,
	corner_summary: list[dict],
	corners: list[dict] | None = None,
) -> dict:
	"""
	Run the full analysis pipeline for a session.

	Three phases:
	  [1] Data gather   — Python, guaranteed first
	  [2] Plan          — orchestrator agent, zero tools, single turn
	  [3] Dispatch      — parallel sub-agents + coaching writer
	"""
	log.info("=== PitWall orchestrator: %s ===", session_id)

	# Phase 1: Gather data (Python — always runs first)
	log.info("[1/3] Gathering session data...")
	try:
		payload = data_gatherer.gather(session_id, corner_summary, corners)
	except Exception as e:
		log.error("Data gathering failed: %s", e)
		return _error_report(f"Data gathering failed: {e}")

	summary = _build_summary(payload, corner_summary)

	# Phase 2: Plan (orchestrator agent — zero tools)
	log.info("[2/3] Planning analysis...")
	try:
		plan = _plan(summary)
	except Exception as e:
		log.error("Planning failed: %s", e)
		# Fallback: deterministic plan from the flags
		plan = _fallback_plan(summary)

	log.info(
		"Plan: %d corners, synthetic=%s",
		len(plan.get("priority_corners", [])),
		plan.get("run_synthetic_lap", False),
	)

	# Phase 3: Dispatch + coaching report
	log.info("[3/3] Dispatching agents...")
	try:
		report = _dispatch(plan, payload)
	except Exception as e:
		log.error("Dispatch failed: %s", e)
		return _error_report(f"Agent dispatch failed: {e}")

	log.info("=== Pipeline complete ===")
	return report


# ---------------------------------------------------------------------------
# Fallback plan — if the orchestrator agent fails, use deterministic logic
# ---------------------------------------------------------------------------

_MIN_TIME_LOSS_MS = 80
_MAX_CORNERS = 12


def _fallback_plan(summary: dict) -> dict:
	"""Deterministic fallback: use flags from data_gatherer directly."""
	log.warning("Using fallback deterministic plan")
	corners = summary.get("corners", [])

	# Select by threshold, at least top 2, cap at max
	priority = [c for c in corners if c["estimated_time_loss_ms"] >= _MIN_TIME_LOSS_MS]
	if not priority:
		priority = corners[:2]
	priority = priority[:_MAX_CORNERS]

	plan_corners = []
	for c in priority:
		analyses = ["corner"]
		if c.get("needs_braking"):
			analyses.append("braking")
		if c.get("needs_balance"):
			analyses.append("balance")
		plan_corners.append({
			"corner_name": c["corner_name"],
			"analyses": analyses,
		})

	return {
		"priority_corners": plan_corners,
		"run_synthetic_lap": summary.get("ref_type") == "self",
	}


def _error_report(message: str) -> dict:
	return {
		"session_summary":  "Analysis pipeline failed.",
		"reference_note":   message,
		"priority_corners": [],
		"full_markdown":    f"## Analysis Failed\n\n{message}",
		"next_action":      "Check logs and rerun the pipeline.",
	}
