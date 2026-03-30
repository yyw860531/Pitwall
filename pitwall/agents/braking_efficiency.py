"""
braking_efficiency.py -- braking zone analysis for one corner.

Uses an agentic loop: receives pre-packaged braking data from the orchestrator,
and can optionally call get_lap_trace for additional channels if needed.
"""

import json
import logging

from pitwall.agents._base import run_agent, load_prompt, TOOLS_BRAKING
from config import config

log = logging.getLogger(__name__)
_SYSTEM = load_prompt("braking_efficiency.txt")


def analyze(corner_payload: dict, car_context: dict | None = None) -> dict | None:
	"""
	Analyse braking efficiency. Returns None if no braking trace available.
	"""
	name  = corner_payload["corner_name"]
	trace = corner_payload.get("best_braking_trace")
	if not trace:
		return None

	log.info("Braking analysis: %s", name)
	payload = {
		"corner_name":        name,
		"distance_range_m":   [corner_payload["start_m"], corner_payload["end_m"]],
		"best_braking_trace": trace,
	}
	if car_context:
		payload["car_context"] = car_context
	user = json.dumps(payload, separators=(",", ":"))

	try:
		result = run_agent(
			_SYSTEM,
			user,
			allowed_tools=TOOLS_BRAKING,
			max_tokens=512,
			model=config.claude_model_fast,
		)
		result.setdefault("corner_name", name)
		return result
	except Exception as e:
		log.error("Braking analysis failed for %s: %s", name, e)
		return {"corner_name": name, "error": str(e)}
