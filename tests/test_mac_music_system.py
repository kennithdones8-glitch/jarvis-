"""Music and system abilities through the real gateway, permissions and approvals, with a stand-in for the Mac."""

import pytest
from test_mac import CTX, run

from jarvis.core import TaskState
from jarvis.core.permissions import Tier
from jarvis.tools import default_registry, mac
from jarvis.tools.mac import MacError, MacTool

MUSIC_RULE = """
[[rules]]
id = "music-controls"
effect = "allow"
tools = ["music"]
actions = ["control", "playlist"]
"""


class FakeMacExtra:
    def __init__(self):
        self.calls = []

    def __call__(self, name, args, timeout):
        self.calls.append((name, args))
        return {"music.now": {"running": True, "state": "playing", "track": {"name": "Song"}, "volume": 60},
                "music.control": {"state": "paused", "track": "Song"}, "music.playlist": {"playing": args.get("name")},
                "music.volume": {"volume": args.get("level")}, "system.volume": {"volume": args.get("level")},
                "system.status": {"battery": {"percent": 80}, "disk": {"free_gb": 50.0}},
                "system.focus": {"focus": args.get("state")}}[name]


@pytest.fixture
def fake():
    return FakeMacExtra()


@pytest.fixture
def kern(make_kernel, tmp_path, fake):
    def _make(extra_policy=""):
        from conftest import DEFAULT_POLICY
        return make_kernel(policy=DEFAULT_POLICY + extra_policy, registry=default_registry(tmp_path / "home", mac_runner=fake))
    return _make


def test_tiers(kern):
    k = kern()
    for tool, action, tier in (("music", "now", Tier.READ), ("music", "control", Tier.ROUTINE), ("music", "playlist", Tier.ROUTINE),
                               ("music", "volume", Tier.ROUTINE), ("system", "status", Tier.READ),
                               ("system", "volume", Tier.ROUTINE), ("system", "focus", Tier.ROUTINE)):
        assert k.registry.action(tool, action).tier is tier, (tool, action)
    assert k.registry.action("system", "shutdown") is None and k.registry.action("system", "settings") is None


def test_reading_status_and_now_playing_never_ask(kern, fake):
    k = kern()
    _, state = run(k, ("Status", "system", "status", {}), ("Now", "music", "now", {}))
    assert state is TaskState.COMPLETED and [c[0] for c in fake.calls] == ["system.status", "music.now"]


def test_playback_asks_unless_the_owner_allowed_it(kern, fake):
    k = kern()
    tid, state = run(k, ("Pause", "music", "control", {"action": "pause"}))
    assert state is TaskState.AWAITING_APPROVAL and fake.calls == []                 # no standing rule: asks first
    k2 = kern(MUSIC_RULE)
    _, state = run(k2, ("Pause", "music", "control", {"action": "pause"}), ("Focus", "music", "playlist", {"name": "Focus"}))
    assert state is TaskState.COMPLETED and [c[0] for c in fake.calls] == ["music.control", "music.playlist"]


def test_volume_and_do_not_disturb_always_ask(kern, fake):
    k = kern(MUSIC_RULE)
    tid, state = run(k, ("Quieter", "system", "volume", {"level": 20}))
    assert state is TaskState.AWAITING_APPROVAL and fake.calls == []
    k.approvals.decide(k.approvals.pending()[0]["id"], approve=True, by="user:test")
    assert k.engine.run(tid) is TaskState.COMPLETED and fake.calls == [("system.volume", {"level": 20})]


@pytest.mark.parametrize("tool,action,args,msg", [
    ("music", "control", {"action": "delete_library"}, "action"),
    ("music", "volume", {"level": 150}, "0 to 100"),
    ("music", "volume", {"level": True}, "0 to 100"),
    ("system", "volume", {"level": -1}, "0 to 100"),
    ("system", "focus", {"state": "sleep"}, "on or off"),
    ("music", "playlist", {"name": ""}, "name"),
])
def test_bad_arguments_refused_before_any_app_is_asked(fake, tool, action, args, msg):
    with pytest.raises(MacError, match=msg):
        getattr(MacTool(runner=fake), f"handle_{tool}")(action, args, CTX)
    assert fake.calls == []


def test_focus_needs_the_owners_shortcut(monkeypatch):
    monkeypatch.setattr(mac, "_cmd", lambda argv, timeout=10: "Morning Routine\n")
    with pytest.raises(MacError, match='make a Shortcut called "JARVIS Focus On"'):
        mac.run_focus_shortcut("on")


def test_status_reads_battery_wifi_and_disk(monkeypatch):
    outputs = {"pmset": "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t76%; discharging; 4:12 remaining present: true",
               "networksetup": "Wi-Fi Power (en0): On", "sw_vers": "14.6.1", "sysctl": "{ sec = 1700000000, usec = 0 }"}
    monkeypatch.setattr(mac, "_cmd", lambda argv, timeout=10: outputs.get(argv[0], ""))
    monkeypatch.setattr(mac, "osascript", lambda name, args, timeout: {"volume": 40})
    s = mac.system_status()
    assert s["battery"] == {"percent": 76, "state": "discharging", "on_power": False, "remaining": "4:12"}
    assert s["wifi"] == {"on": True} and s["macos"] == "14.6.1" and s["disk"]["total_gb"] > 0 and s["volume"] == 40


def test_example_policy_allows_music_playback_only():
    import tomllib
    from pathlib import Path
    pol = tomllib.loads((Path(__file__).resolve().parents[1] / "config" / "policy.example.toml").read_text())
    rule = next(r for r in pol["rules"] if r["id"] == "music-controls")
    assert rule["effect"] == "allow" and rule["tools"] == ["music"] and rule["actions"] == ["control", "playlist"]


@pytest.mark.parametrize("text,expected", [
    ("pause the music", ("music", "control", {"action": "pause"})),
    ("Play my Focus playlist", ("music", "playlist", {"name": "Focus"})),
    ("skip", ("music", "control", {"action": "next"})),
    ("How's my battery?", ("system", "status", {})),
    ("set volume to 30", ("system", "volume", {"level": 30})),
    ("music volume 250", ("music", "volume", {"level": 100})),
    ("turn off do not disturb", ("system", "focus", {"state": "off"})),
])
def test_chat_commands_are_recognised(text, expected):
    from jarvis.intent import classify
    r = classify(text)
    assert r["mode"] == "command" and (r["tool"], r["action"], r["args"]) == expected


@pytest.mark.parametrize("text", ["How do I play chess?", "What is a playlist?", "Explain how volume knobs work",
                                  "Write a song about rain"])
def test_ordinary_questions_are_not_commands(text):
    from jarvis.intent import classify
    assert classify(text)["mode"] != "command"


def test_command_replies_are_worded_from_the_result_without_a_model():
    from jarvis.server.app import _say_mac
    assert _say_mac("system", "status", {}, {"battery": {"percent": 76, "state": "discharging", "remaining": "4:12"},
                                             "wifi": {"on": True}, "disk": {"free_gb": 50.0, "total_gb": 500.0}}) == \
        "Your Mac: battery 76% (discharging, 4:12 left), Wi-Fi on, 50.0 GB free of 500.0 GB."
    assert _say_mac("music", "now", {}, {"running": False}) == "Music isn't open."


def test_command_endpoint_runs_only_music_and_system(dash):
    from test_dashboard import call
    d, *_ = dash
    assert call(d, "/api/command", {"tool": "fs", "action": "delete", "args": {"path": "/"}})[0] == 400


def test_direct_command_asks_then_runs_once_approved(kern, fake):
    from jarvis.core.tools import ApprovalRequired
    k = kern()
    with pytest.raises(ApprovalRequired) as exc:
        k.gateway.invoke("system", "volume", {"level": 25}, summary="Mac volume to 25%")
    assert fake.calls == []
    k.approvals.decide(exc.value.approval_id, approve=True, by="user:test")
    assert k.gateway.invoke("system", "volume", {"level": 25})["volume"] == 25        # the approval is used once
    with pytest.raises(ApprovalRequired):
        k.gateway.invoke("system", "volume", {"level": 25})                            # asking again needs a new OK
    assert len(fake.calls) == 1
