"""Ideas page decisions are one tap once signed in; redesign CSS never hides dialog buttons."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"


def test_ideas_page_decides_in_one_tap_and_points_to_sign_in():
    js = (STATIC / "proposals.js").read_text()
    decide = js.split("async function decide(id, what, btn) {")[1].split("\n}\n")[0]
    assert 'await post(`/api/proposals/${encodeURIComponent(id)}/${what}`, {});' in decide
    assert "Sign in on the Home page first" in decide and "stepup" not in js


def test_server_no_longer_asks_a_fingerprint_for_idea_decisions():
    from jarvis.remote.mac import MAC_STEP_UP
    from jarvis.remote.passkeys import STEP_UP, needs_step_up
    path = "/api/proposals/prop_x/approve"
    assert not needs_step_up(path, {}, STEP_UP, lambda _: 1) and not needs_step_up(path, {}, MAC_STEP_UP, lambda _: 1)


def test_the_dangerous_few_and_only_high_risk_approvals_need_the_fingerprint():
    from jarvis.remote.passkeys import STEP_UP, needs_step_up
    tiers = {"low": 1, "ext": 3, "high": 4}
    need = lambda path, body=None: needs_step_up(path, body or {}, STEP_UP, tiers.__getitem__)  # noqa: E731
    assert need("/api/release") and need("/api/memory/m1/delete") and need("/api/memory/m1/edit")
    assert need("/api/devices/d1/revoke") and need("/api/memory/forget", {"confirm": True})
    assert not need("/api/memory/forget", {"confirm": False})  # a preview changes nothing
    assert need("/api/approvals/high", {"approve": True})
    assert not need("/api/approvals/high", {"approve": False})  # saying no is one tap
    assert not need("/api/approvals/low", {"approve": True}) and not need("/api/approvals/ext", {"approve": True})
    assert not need("/api/approvals/missing", {"approve": True})  # the request itself fails
    for one_tap in ("/api/plan/abc/run", "/api/tasks/t/steps/s/resolve", "/api/proposals/p/approve", "/api/stop"):
        assert not need(one_tap), one_tap
    js = (STATIC / "app.js").read_text()
    assert "/api\\/plan" not in js.split("const FACE_ID = [")[1].split("];")[0]


def test_redesign_css_only_targets_the_main_column():
    """Dialogs use class "center" for their button row; a bare .center rule once hid those buttons outside Home."""
    css = (STATIC / "app.css").read_text()
    redesign = css.split("Stage 1: application shell")[1]
    bare = re.findall(r"(?<![\w>-])(?<!> )\.center(?=[\s>{,:)\[])", redesign)
    assert not bare, f"{len(bare)} redesign rules match any element with class center"


def test_sign_in_screen_keeps_emergency_stop_one_click_away():
    """The sign-in box blocks the rest of the page (including the header's Emergency stop), so it carries its own."""
    js = (STATIC / "app.js").read_text()
    signin = js.split("function showSignIn() {")[1].split("\n}\n")[0]
    assert 'api("/api/stop", { reason: "stopped from the sign-in screen" })' in signin
    assert 'h("div", { class: "row mt center" }, btn, stop)' in signin
    from jarvis.server.app import PRE_SIGNIN_POST
    assert "/api/stop" in PRE_SIGNIN_POST  # and the server accepts it before sign-in
