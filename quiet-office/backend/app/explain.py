"""Plain-language explanation of a run, written by an OpenAI model.

The model is only a narrator. It is handed the facts (what was sent to Allsolve, what came
back, the scores) and asked to explain them for someone who is not an engineer. It does not
compute anything and is told not to invent numbers.
"""

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .config import get_settings

logger = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MAX_SOLVER_LINES = 12
MAX_LOG_ENTRIES = 60

SYSTEM_PROMPT = """You explain one run of QuietOffice to an office manager who is not an engineer.

QuietOffice decides where to put a few acoustic screens in an open office so that the places
marked as quiet get as little noise as possible. The run you explain is a real physics
simulation of sound waves, done in the cloud on Quanscient Allsolve.

You get a JSON object with the office, the settings, the result, and the run log: every
request sent to Allsolve and every answer. "run_finished_at" says when the run ended. If
"page_changed_since_run" is true, the user has changed the office or the settings after this
run: say in the first sentence that you are describing that earlier run and that it may no
longer match what is on screen.

Write in plain, direct language. No jargon; if a technical word is needed, explain it in a few
words. Use only numbers that appear in the JSON. Never invent a number, a job or a step.
Levels are in dB; the noise score is relative, where 100 is the office with no screens and
lower is quieter.

Use exactly these four short sections, each with a heading on its own line:

What we did
What the simulation found
What to do
How sure we can be

In "What we did", say how many layouts and solves were run on Allsolve, how long the search
took if the log says so, and that the project can be opened in Allsolve.
In "What the simulation found", lead with the quiet zones if there are any: they are what the
search minimised. Desks are reported but did not steer it.
In "How sure we can be", be honest: the model is simplified, and the score is a comparison
between layouts and not a measured dB reduction.
If the run failed or the log shows an error, say so first and explain what went wrong in
simple words.

Keep the whole answer under 230 words. Plain text only: no markdown symbols, no bullet marks."""


def is_configured() -> bool:
    return bool(get_settings().openai_api_key)


def summarise_log(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the log short enough to send: all steps, only a few raw solver lines, no bulky data."""
    kept, solver_lines = [], 0
    for entry in entries:
        if entry["kind"] == "solver":
            solver_lines += 1
            if solver_lines > MAX_SOLVER_LINES:
                continue
        item = {"t": entry["elapsed_s"], "kind": entry["kind"], "step": entry["step"], "message": entry["message"]}
        kept.append(item)
    if len(kept) > MAX_LOG_ENTRIES:
        kept = kept[: MAX_LOG_ENTRIES // 2] + kept[-MAX_LOG_ENTRIES // 2 :]
    return kept


def explain(context: Dict[str, Any], log_entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, str]:
    """Ask the model for the explanation. Blocking: call it from a worker thread."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("No OpenAI key configured. Add OPENAI_API_KEY to .env and restart the backend.")

    facts = dict(context)
    if log_entries:
        facts["run_log"] = summarise_log(log_entries)
    body = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(facts, separators=(",", ":"))[:24000]},
        ],
    }
    request = urllib.request.Request(
        OPENAI_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.openai_api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except Exception:
            detail = detail[:300]
        raise RuntimeError(f"OpenAI refused the request ({e.code}): {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach OpenAI: {e.reason}") from e

    text = payload["choices"][0]["message"]["content"].strip()
    return {"text": text, "model": payload.get("model", settings.openai_model)}
