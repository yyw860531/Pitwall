"""
_base.py -- shared Claude API helper for all analysis agents.

All analysis agents import call_claude_json and load_prompt from here.
"""

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


def load_prompt(name: str) -> str:
    """Load a system prompt from prompts/<name>.txt."""
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def call_claude_json(system: str, user: str, max_tokens: int = 2048) -> dict:
    """
    Call Claude and parse the JSON response.
    Retries once with a stricter reminder if the response is not valid JSON.
    """
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    for attempt in range(2):
        if attempt == 1:
            user = user + "\n\nIMPORTANT: Return ONLY valid JSON. No text before or after."

        response = client.messages.create(
            model=config.claude_model,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        text = response.content[0].text.strip()

        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            if attempt == 0:
                log.warning("JSON parse failed (attempt 1): %s -- retrying", e)
                continue
            raise ValueError(
                f"Agent returned invalid JSON after retry: {e}\nRaw response:\n{text[:500]}"
            ) from e

    raise RuntimeError("Unexpected exit from retry loop")
