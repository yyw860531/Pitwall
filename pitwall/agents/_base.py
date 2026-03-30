"""
_base.py -- Agent foundation for PitWall analysis agents.

Provides:
  - run_agent(): Agentic loop with tool-use support
  - Tool registry: maps MCP tool names to server functions
  - Per-agent tool filtering (Option B: restricted visibility)
  - load_prompt(): Load system prompts from prompts/*.txt

Architecture:
  Agents call server functions directly via the tool registry.
  The same functions are also exposed via MCP for external clients.
  This keeps agents fast (no IPC) while maintaining the MCP contract.

  When agents need data beyond what the orchestrator pre-packages,
  they call tools (e.g. get_lap_trace for additional channels).
  The agentic loop handles Claude's tool_use requests automatically.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import anthropic

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))
from config import config  # noqa: E402

log = logging.getLogger(__name__)
_PROMPTS_DIR = _ROOT / "prompts"

# Max tool-use round trips before forcing a final answer
_MAX_TOOL_TURNS = 5


def load_prompt(name: str) -> str:
	"""Load a system prompt from prompts/<name>.txt."""
	path = _PROMPTS_DIR / name
	if not path.exists():
		raise FileNotFoundError(f"Prompt file not found: {path}")
	return path.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Tool registry -- maps MCP tool names to Python functions + Anthropic schemas
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: dict[str, dict] = {}


def _register_tool(name: str, func, description: str, input_schema: dict):
	_TOOL_REGISTRY[name] = {
		"func": func,
		"definition": {
			"name": name,
			"description": description,
			"input_schema": input_schema,
		},
	}


def _init_registry():
	"""Import server functions and register them as callable tools."""
	if _TOOL_REGISTRY:
		return  # already initialised

	from pitwall.server import (  # noqa: E402
		get_session_metadata,
		list_laps,
		get_lap_trace,
		get_ac_car_data,
		get_ac_track_line,
	)

	_register_tool(
		"get_session_metadata",
		get_session_metadata,
		"Get session metadata: car, track, laps, sector times, theoretical best.",
		{
			"type": "object",
			"properties": {
				"session_id": {
					"type": "string",
					"description": "Session ID, e.g. '28032026-152157'",
				},
			},
			"required": ["session_id"],
		},
	)

	_register_tool(
		"list_laps",
		list_laps,
		"List all laps for a session with per-lap metadata and sector times.",
		{
			"type": "object",
			"properties": {
				"session_id": {
					"type": "string",
					"description": "Session ID",
				},
			},
			"required": ["session_id"],
		},
	)

	_register_tool(
		"get_lap_trace",
		get_lap_trace,
		(
			"Get raw telemetry samples for a lap within a distance range. "
			"Channels: speed_kph, throttle_pct, brake_pct, steering_deg, "
			"gear, rpm, lat_g, long_g, slip_fl/fr/rl/rr. "
			"Always specify the tightest distance range you need."
		),
		{
			"type": "object",
			"properties": {
				"lap_id": {
					"type": "string",
					"description": "Lap ID, e.g. '28032026-152157_lap4'",
				},
				"channels": {
					"type": "array",
					"items": {"type": "string"},
					"description": "Telemetry channels to return",
				},
				"distance_start_m": {
					"type": "number",
					"description": "Start distance in metres (default 0)",
				},
				"distance_end_m": {
					"type": "number",
					"description": "End distance in metres (default 9999)",
				},
			},
			"required": ["lap_id", "channels"],
		},
	)

	_register_tool(
		"get_ac_car_data",
		get_ac_car_data,
		"Read AC car physics: mass, grip, downforce, drivetrain. Requires AC_ROOT.",
		{
			"type": "object",
			"properties": {
				"car_id": {
					"type": "string",
					"description": "AC car ID, e.g. 'ks_bmw_m4_gt3'",
				},
			},
			"required": ["car_id"],
		},
	)

	_register_tool(
		"get_ac_track_line",
		get_ac_track_line,
		(
			"Parse AC track racing line: XYZ waypoints, curvature, detected corners. "
			"Requires AC_ROOT."
		),
		{
			"type": "object",
			"properties": {
				"track_id": {
					"type": "string",
					"description": "AC track ID, e.g. 'ks_vallelungaclub_circuit'",
				},
			},
			"required": ["track_id"],
		},
	)


def _get_tool_definitions(allowed: list[str] | None) -> list[dict]:
	"""Return Anthropic tool definitions filtered by allowed names."""
	_init_registry()
	if not allowed:
		return []
	return [
		_TOOL_REGISTRY[name]["definition"]
		for name in allowed
		if name in _TOOL_REGISTRY
	]


def _call_tool(name: str, arguments: dict):
	"""Execute a registered tool by name."""
	_init_registry()
	if name not in _TOOL_REGISTRY:
		raise ValueError(f"Unknown tool: {name}")
	return _TOOL_REGISTRY[name]["func"](**arguments)


# ---------------------------------------------------------------------------
# Per-agent tool allowlists (Option B: restricted visibility)
# ---------------------------------------------------------------------------

TOOLS_CORNER_ANALYSIS = ["get_lap_trace", "get_session_metadata"]
TOOLS_BRAKING         = ["get_lap_trace"]
TOOLS_BALANCE         = ["get_lap_trace"]
TOOLS_SYNTHETIC_LAP   = ["get_ac_car_data", "get_ac_track_line"]
TOOLS_COACHING_WRITER: list[str] = []  # receives pre-computed results only


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> dict:
	"""Extract JSON from Claude's response, stripping markdown fences."""
	text = re.sub(r"^```(?:json)?\s*", "", text)
	text = re.sub(r"\s*```$", "", text)
	return json.loads(text.strip())


# ---------------------------------------------------------------------------
# Agentic loop -- runs Claude with optional tool-use
# ---------------------------------------------------------------------------

def run_agent(
	system: str,
	user_message: str,
	allowed_tools: list[str] | None = None,
	max_tokens: int = 2048,
	model: str | None = None,
	max_turns: int = _MAX_TOOL_TURNS,
) -> dict:
	"""
	Run a PitWall agent in an agentic loop.

	The agent receives a system prompt and user message. If allowed_tools
	is provided, the agent can call server functions (via the tool registry)
	on each turn. The loop continues until Claude returns a final text answer
	or max_turns is exceeded.

	Returns the parsed JSON response dict.
	"""
	if not config.anthropic_api_key:
		raise EnvironmentError(
			"ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
		)

	active_model = model or config.claude_model
	client = anthropic.Anthropic(api_key=config.anthropic_api_key)
	tools = _get_tool_definitions(allowed_tools)

	messages = [{"role": "user", "content": user_message}]

	for turn in range(max_turns + 1):
		kwargs: dict = {
			"model": active_model,
			"system": system,
			"messages": messages,
			"max_tokens": max_tokens,
		}
		if tools:
			kwargs["tools"] = tools

		response = client.messages.create(**kwargs)

		# Check for tool-use blocks
		tool_blocks = [b for b in response.content if b.type == "tool_use"]

		if not tool_blocks:
			# Final answer -- extract text and parse JSON
			text = "".join(
				b.text for b in response.content if hasattr(b, "text")
			).strip()

			try:
				return _parse_json(text)
			except json.JSONDecodeError as e:
				# One retry: ask Claude to fix its JSON
				if turn < max_turns:
					log.warning("JSON parse failed (turn %d): %s -- retrying", turn, e)
					messages.append({"role": "assistant", "content": response.content})
					messages.append({
						"role": "user",
						"content": (
							"Your response was not valid JSON. "
							"Return ONLY the JSON object, no other text."
						),
					})
					continue
				raise ValueError(
					f"Agent returned invalid JSON after retry: {e}\n"
					f"Raw response:\n{text[:500]}"
				) from e

		# Execute tool calls via the registry
		log.debug("  Turn %d: %d tool call(s)", turn + 1, len(tool_blocks))
		messages.append({"role": "assistant", "content": response.content})

		tool_results = []
		for block in tool_blocks:
			log.info(
				"  [tool] %s(%s)",
				block.name,
				json.dumps(block.input, separators=(",", ":"))[:120],
			)
			try:
				result = _call_tool(block.name, block.input)
				content = json.dumps(result, separators=(",", ":"))
			except Exception as e:
				log.error("  [tool] %s failed: %s", block.name, e)
				content = json.dumps({"error": str(e)})

			tool_results.append({
				"type": "tool_result",
				"tool_use_id": block.id,
				"content": content,
			})

		messages.append({"role": "user", "content": tool_results})

	raise RuntimeError(
		f"Agent exceeded {max_turns} tool-use turns without producing a final answer"
	)
