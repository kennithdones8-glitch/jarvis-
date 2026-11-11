"""Conversation mode: hands-free turns, but the microphone is only ever opened by your tap or by the turn after a
reply in a conversation you started; it's never left on across visits and there is no always-listening wake word.
Replies still use on-device voices only."""

import re
from pathlib import Path

JS = (Path(__file__).parents[1] / "src/jarvis/server/static/app.js").read_text()
HTML = (Path(__file__).parents[1] / "src/jarvis/server/static/index.html").read_text()


def _fn(name):
    return JS.split(f"function {name}(")[1].split("\n}\n")[0]


def test_microphone_opens_only_in_toggle_mic():
    assert JS.count("getUserMedia(") == 1 and "getUserMedia(" in _fn("toggleMic")
    assert "SpeechRecognition" not in JS and "webkitSpeechRecognition" not in JS   # no browser (cloud) recogniser


def test_conversation_is_never_remembered_or_started_by_itself():
    assert "jarvis-convo" not in JS
    assert "voice.convo = false" in _fn("endConvo")
    assert re.search(r"convo: false, live: false", JS)
    assert 'id="convo"' in HTML and 'aria-pressed="false"' in HTML.split('id="convo"')[1].split(">")[0]


def test_conversation_ends_on_words_silence_or_hiding():
    assert re.search(r"CONVO_END = /\^\(stop\|goodbye", JS)
    assert "QUIET_MS = 8000" in JS and "document.hidden" in _fn("autoStop")
    assert "CONVO_END.test" in _fn("finishRecording")


def test_replies_still_use_on_device_voices_and_prefer_natural_ones():
    assert "v.localService" in _fn("localVoices")
    assert "premium|enhanced" in _fn("say")
