"""The avatar's central state machine (static/avatar-state.js), run for real in Node with a fake clock.

Skipped when Node isn't installed (it is not a project dependency); the source-level checks below always run.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"
SM = STATIC / "avatar-state.js"
NODE = shutil.which("node")

HARNESS = """
const { createMachine, PROFILE } = require(%s);
let t = 0; const m = createMachine({ now: () => t });
const steps = %s, out = [];
for (const [at, op, arg] of steps) {
  t = at;
  const o = op === "in" ? m.input(arg) : op === "tick" ? m.tick() : op === "preview" ? m.previewState(arg)
          : op === "life" ? m.setLifecycle(arg) : m.output;
  out.push([o.state, o.profile, o.preview, o.lifecycle]);
}
console.log(JSON.stringify(out));
"""


def run(steps):
    if not NODE:
        pytest.skip("node not installed")
    code = HARNESS % (json.dumps(str(SM)), json.dumps(steps))
    res = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(res.stdout)


def test_every_renderer_state_has_a_profile_and_the_brief_profiles_exist():
    out = run([[0, "in", "idle"]])
    assert out[0][:2] == ["idle", "idle"]
    src = SM.read_text()
    for profile in ("dormant", "idle", "listening", "thinking", "researching", "planning", "executing", "speaking",
                    "success", "warning", "error", "recovering", "approval", "halted"):
        assert f'"{profile}"' in src or f"{profile}:" in src, profile
    assert '"materializing"' in src and '"dematerializing"' in src


def test_critical_states_replace_routine_activity_at_once():
    out = run([[0, "in", "reasoning"], [100, "in", "error"], [200, "in", "halted"]])
    assert [o[0] for o in out] == ["reasoning", "error", "halted"]


def test_routine_activity_cannot_overwrite_an_error_before_its_minimum_time():
    out = run([[0, "in", "error"], [500, "in", "writing"], [2000, "tick", None], [2600, "tick", None]])
    assert [o[0] for o in out] == ["error", "error", "error", "writing"]


def test_success_ends_on_its_own_after_four_seconds_even_if_the_input_still_says_completed():
    out = run([[0, "in", "completed"], [3000, "in", "completed"], [4100, "tick", None], [5000, "in", "completed"]])
    assert [o[1] for o in out] == ["success", "success", "idle", "idle"]


def test_a_new_success_after_other_activity_shows_again():
    out = run([[0, "in", "completed"], [4100, "tick", None], [5000, "in", "executing"], [6000, "in", "completed"]])
    assert [o[1] for o in out] == ["success", "idle", "executing", "success"]


def test_stale_activity_falls_back_to_idle_but_standing_alerts_do_not():
    out = run([[0, "in", "executing"], [5000, "tick", None], [10100, "tick", None]])
    assert [o[0] for o in out] == ["executing", "executing", "idle"]
    out = run([[0, "in", "warning"], [20000, "tick", None]])
    assert out[-1][0] == "warning"   # a health warning is a standing condition, not "activity"


def test_no_flicker_between_routine_states():
    out = run([[0, "in", "writing"], [200, "in", "idle"], [800, "tick", None]])
    assert [o[0] for o in out] == ["writing", "writing", "idle"]


def test_preview_is_flagged_lasts_at_most_ten_seconds_and_yields_to_a_real_critical_state():
    out = run([[0, "in", "idle"], [100, "preview", "executing"], [5000, "tick", None], [10200, "tick", None]])
    assert out[1] == ["executing", "executing", True, None] and out[2][2] is True
    assert out[3][:3] == ["idle", "idle", False]
    out = run([[0, "in", "idle"], [100, "preview", "coding"], [200, "in", "error"]])
    assert out[2][:3] == ["error", "error", False]
    out = run([[0, "in", "error"], [100, "preview", "coding"]])
    assert out[1][:3] == ["error", "error", False]   # no preview over a real error


def test_lifecycle_phases_are_reported():
    out = run([[0, "life", "materializing"], [10, "in", "idle"], [20, "life", None]])
    assert out[0][3] == "materializing" and out[2][3] is None


def test_the_bridge_routes_every_state_through_the_machine():
    av = (STATIC / "avatar.js").read_text()
    assert "const SM = window.JarvisAvatarState ? window.JarvisAvatarState.createMachine() : null;" in av
    assert "show(SM.input(state)); schedule();" in av
    html = (STATIC / "index.html").read_text()
    assert html.index("/static/avatar-state.js") < html.index("/static/avatar.js")


def test_queued_work_is_never_shown_as_active():
    js = (STATIC / "app.js").read_text()
    assert 'case "queued": return "idle";' in js
    assert 'kind: "Queued"' in js and "nothing is running yet" in js
