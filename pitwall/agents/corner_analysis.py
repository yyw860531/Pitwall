"""
corner_analysis.py -- analyses best vs reference trace for one corner.

Uses an agentic loop: receives pre-packaged corner data from the orchestrator,
and can optionally call get_lap_trace for additional channels if needed.
"""

import json
import logging

from pitwall.agents._base import run_agent, load_prompt, TOOLS_CORNER_ANALYSIS
from config import config

log = logging.getLogger(__name__)
_SYSTEM = load_prompt("corner_analysis.txt")


def analyze(corner_payload: dict, car_context: dict | None = None) -> dict:
	"""
	Analyse a single corner. Returns a CornerAnalysisResult dict.
	Returns an error dict on failure so the pipeline keeps running.
	"""
	name = corner_payload["corner_name"]
	log.info("Corner analysis: %s", name)

	payload = {
		"corner_name":      name,
		"distance_range_m": [corner_payload["start_m"], corner_payload["end_m"]],
		"best_trace":       corner_payload["best_trace"],
		"ref_trace":        corner_payload["ref_trace"],
	}
	if corner_payload.get("sector_delta_ms") is not None:
		payload["sector_delta_ms"] = corner_payload["sector_delta_ms"]
	if car_context:
		payload["car_context"] = car_context

	user = json.dumps(payload, separators=(",", ":"))

	try:
		result = run_agent(
			_SYSTEM,
			user,
			allowed_tools=TOOLS_CORNER_ANALYSIS,
			max_tokens=1024,
			model=config.claude_model_fast,
		)
		result.setdefault("corner_name", name)
		return result
	except Exception as e:
		log.error("Corner analysis failed for %s: %s", name, e)
		return {"corner_name": name, "error": str(e), "estimated_time_gain_ms": 0}
