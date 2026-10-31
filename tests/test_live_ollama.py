"""Live test against a real local Ollama. Opt-in: run on the Mac with

    JARVIS_LIVE_OLLAMA=llama3.2:3b uv run pytest tests/test_live_ollama.py -s

Warms the model up first, then reports Ollama's own timing: load, prompt reading and generation speed.
"""

import os

import pytest

from jarvis.models import ChatRequest, Message, parse_json_output
from jarvis.models.http import request_json
from jarvis.models.providers import OllamaProvider
from jarvis.models.types import ModelInfo

MODEL = os.environ.get("JARVIS_LIVE_OLLAMA")
HOST = "http://127.0.0.1:11434"
pytestmark = pytest.mark.skipif(not MODEL, reason="set JARVIS_LIVE_OLLAMA=<model> to run against real Ollama")


def test_real_ollama_round_trip():
    info = ModelInfo(MODEL, frozenset({"chat", "json"}), 8192, 2, 3)
    p = OllamaProvider("ollama", HOST, {MODEL: info})
    assert MODEL in p.available_models(), f"{MODEL} is not installed (ollama pull {MODEL})"
    r = p.chat(MODEL, ChatRequest((Message("user", 'Reply with JSON {"capital": <capital of France>}'),),
                                  max_tokens=40, json_mode=True))
    assert "paris" in parse_json_output(r.text, ("capital",))["capital"].lower()


def test_real_ollama_speed():
    prompt = "Write five sentences about the planet Mars."
    payload = {"model": MODEL, "prompt": prompt, "stream": False, "keep_alive": "30m",
               "options": {"num_predict": 120, "temperature": 0}}
    cold = request_json("POST", f"{HOST}/api/generate", payload, timeout=600)
    warm = request_json("POST", f"{HOST}/api/generate", payload, timeout=600)
    s = 1e9
    gen = warm["eval_count"] / (warm["eval_duration"] / s)
    read = warm.get("prompt_eval_count", 0) / max(warm.get("prompt_eval_duration", 1) / s, 1e-9)
    print(f"\n{MODEL}: load {cold.get('load_duration', 0) / s:.1f}s (cold) · "
          f"generation {gen:.1f} tok/s · prompt reading {read:.1f} tok/s · "
          f"{warm['eval_count']} tokens in {warm['total_duration'] / s:.1f}s warm")
    assert gen > 0
