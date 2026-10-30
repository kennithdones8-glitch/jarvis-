"""Live test against a real local Ollama. Opt-in: run on the Mac with

    JARVIS_LIVE_OLLAMA=llama3.2:3b uv run pytest tests/test_live_ollama.py -s

It reports real latency and tokens/second for this hardware.
"""

import os

import pytest

from jarvis.models import ChatRequest, Message, parse_json_output
from jarvis.models.providers import OllamaProvider
from jarvis.models.types import ModelInfo

MODEL = os.environ.get("JARVIS_LIVE_OLLAMA")
pytestmark = pytest.mark.skipif(not MODEL, reason="set JARVIS_LIVE_OLLAMA=<model> to run against real Ollama")


def test_real_ollama_round_trip_and_speed():
    info = ModelInfo(MODEL, frozenset({"chat", "json"}), 8192, 2, 3)
    p = OllamaProvider("ollama", "http://127.0.0.1:11434", {MODEL: info})
    assert MODEL in p.available_models(), f"{MODEL} is not installed (ollama pull {MODEL})"
    r = p.chat(MODEL, ChatRequest((Message("user", 'Reply with JSON {"capital": <capital of France>}'),),
                                  max_tokens=40, json_mode=True))
    assert "paris" in parse_json_output(r.text, ("capital",))["capital"].lower()
    tps = r.usage.output_tokens / r.latency_s if r.latency_s else 0
    print(f"\n{MODEL}: {r.latency_s:.1f}s total, {r.usage.output_tokens} tokens out, ~{tps:.1f} tok/s")
