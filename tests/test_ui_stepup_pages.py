"""The Ideas page asks for Face ID / Touch ID like the dashboard; redesign CSS never hides dialog buttons."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "server" / "static"


def test_ideas_page_confirms_with_face_id_or_touch_id_when_the_device_has_it():
    js = (STATIC / "proposals.js").read_text()
    decide = js.split("async function decide(id, what, btn) {")[1].split("\n}\n")[0]
    assert 'post("/api/stepup/options", { path, body: {} })' in decide
    assert "challengeId: o.challengeId, assertion:" in decide and "signature: b64u.fromBuf(a.response.signature)" in decide
    bio = js.split("async function loadBio() {")[1].split("\n}\n")[0]
    assert 'st.remote && st.remote.this_device ? "Face ID"' in bio and 'st.touch_id && st.touch_id.enabled ? "Touch ID"' in bio
    assert "loadBio().then(load);" in js


def test_server_still_requires_the_confirmation_for_idea_decisions():
    from jarvis.remote.passkeys import STEP_UP
    from jarvis.remote.mac import MAC_STEP_UP
    path = "/api/proposals/prop_x/approve"
    assert any(re.fullmatch(p, path) for p in STEP_UP) and any(re.fullmatch(p, path) for p in MAC_STEP_UP)


def test_redesign_css_only_targets_the_main_column():
    """Dialogs use class "center" for their button row; a bare .center rule once hid those buttons outside Home."""
    css = (STATIC / "app.css").read_text()
    redesign = css.split("Stage 1: application shell")[1]
    bare = re.findall(r"(?<![\w>-])(?<!> )\.center(?=[\s>{,:)\[])", redesign)
    assert not bare, f"{len(bare)} redesign rules match any element with class center"
