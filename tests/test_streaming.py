"""Live replies: a local model's answer is shown as it's written. Same answer as /api/chat; display only."""

import json
import urllib.request

import pytest

from model_servers import start_ollama
from test_dashboard import CFG, call

from jarvis.models import ChatRequest, Message
from jarvis.models.providers import OllamaProvider
from jarvis.models.types import ModelInfo


def stream(d, body, *, headers=None, host=None, cookie="jarvis_session=test-token"):
    h = {"Host": host or f"localhost:{d.port}", "Content-Type": "application/json", "X-Requested-By": "jarvis",
         "Cookie": cookie, **(headers or {})}
    req = urllib.request.Request(f"http://127.0.0.1:{d.port}/api/chat/stream", data=json.dumps(body).encode(),
                                 headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.headers.get("Content-Type"), [json.loads(x) for x in r.read().decode().splitlines() if x.strip()]
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), []


@pytest.fixture
def ollama():
    s = start_ollama(installed=["m"])
    s.reply = lambda body: "The quick brown fox jumps."
    yield s
    s.stop()


def provider(url):
    info = ModelInfo(id="m", capabilities=frozenset({"chat"}), context_tokens=4096, quality=3, speed=3)
    return OllamaProvider("ollama", url, {"m": info})


def test_provider_streams_the_same_answer(ollama):
    p, pieces = provider(ollama.url), []
    req = ChatRequest((Message("user", "hi"),))
    streamed = p.chat("m", req, on_token=pieces.append)
    whole = p.chat("m", req)
    assert "".join(pieces) == streamed.text == whole.text == "The quick brown fox jumps."
    assert len(pieces) > 3 and streamed.usage.output_tokens == len(pieces)
    assert ollama.received[0]["body"]["stream"] is True and ollama.received[1]["body"]["stream"] is False


def test_viewer_leaving_stops_generation_and_is_not_a_model_failure(ollama):
    from jarvis.models.types import ProviderError

    def gone(piece):
        raise BrokenPipeError("page closed")
    with pytest.raises(BrokenPipeError):  # not ProviderUnavailable: the router must not retry another model
        provider(ollama.url).chat("m", ChatRequest((Message("user", "hi"),)), on_token=gone)
    assert not issubclass(BrokenPipeError, ProviderError)


def test_dashboard_streams_then_sends_the_usual_result(dash):
    d, *_ = dash
    status, ctype, lines = stream(d, {"message": "hi", "history": []})
    assert status == 200 and ctype.startswith("application/x-ndjson")
    pieces = [x["t"] for x in lines if "t" in x]
    done = lines[-1]["done"]
    assert len(pieces) > 1 and "".join(pieces) == done["text"] == "Hello, I am JARVIS."
    plain = json.loads(call(d, "/api/chat", {"message": "hi", "history": []})[2])
    assert plain["text"] == done["text"] and set(plain) == set(done)  # same answer, same shape


def test_emergency_stop_cuts_a_reply_off_mid_sentence(make_kernel, tmp_path):
    from jarvis.server import Dashboard
    holder = {}
    server = start_ollama(installed=["planner:7b"])

    def reply(body):  # the stop is pressed while the model is answering
        holder["k"].engine.emergency_stop(by="user:test", reason="t")
        return "one two three four five six"
    server.reply = reply
    (tmp_path / "jarvis.toml").write_text(CFG.format(url=server.url))
    holder["k"] = k = make_kernel(config_path=tmp_path / "jarvis.toml")
    d = Dashboard(k, port=0, token="test-token", poll_s=0.05)
    d.start()
    try:
        status, _, lines = stream(d, {"message": "hi", "history": []})
        assert status == 200 and lines[-1]["done"]["stopped"] is True
        assert not any("t" in x for x in lines)  # nothing more was shown once the stop was on
        assert len(server.received) == 1  # and no other model was tried
    finally:
        d.shutdown()
        server.stop()


def test_stream_has_the_usual_protections(dash):
    d, *_ = dash
    assert stream(d, {"message": "hi"}, cookie="")[0] == 401
    assert stream(d, {"message": "hi"}, headers={"X-Requested-By": "x"})[0] == 403
    assert stream(d, {"message": "hi"}, headers={"Origin": "https://evil.example"})[0] == 403
    assert stream(d, {"message": ""})[0] == 400
