"""Phase 3a dashboard: intelligence modes, Stop / Copy / Regenerate / Retry / Edit, and live stages.

Checked here from the page source the dashboard serves; behaviour was also checked in a headless browser."""

from test_dashboard import call


def page(d):
    return (call(d, "/")[2].decode(), call(d, "/static/app.js")[2].decode(), call(d, "/static/app.css")[2].decode())


def fn(js, name):
    return js.split(f"function {name}(")[1].split("\n}\n")[0]


def test_mode_selector_and_stop_button_are_in_the_command_box(dash):
    d, _, _ = dash
    html, _, _ = page(d)
    form = html.split('id="cmdform"')[1].split("</form>")[0]
    assert 'id="stopgen"' in form and 'id="send"' in form
    modes = form.split('id="intelmodes"')[1].split("</div>")[0]
    assert 'role="radiogroup"' in form and [m for m in ("quick", "balanced", "deep") if f'data-intel="{m}"' in modes] \
        == ["quick", "balanced", "deep"]
    assert 'data-intel="balanced" aria-checked="true"' in modes  # Balanced is the default


def test_chat_sends_the_chosen_mode_and_a_clean_history(dash):
    d, _, _ = dash
    _, js, _ = page(d)
    assert "mode: ui.intel" in fn(js, "submitCommand")
    hist = fn(js, "historyBefore")
    for excluded in ("!m.error", "!m.consent", "!m.help", "!m.welcome", "!m.briefing"):
        assert excluded in hist, excluded


def test_stop_aborts_the_stream_and_keeps_what_was_written(dash):
    d, _, _ = dash
    _, js, _ = page(d)
    stream = fn(js, "streamChat")
    assert "new AbortController()" in stream and "signal: controller.signal" in stream
    assert 'e.name === "AbortError"' in stream and "partial: live.text" in stream
    assert "ui.abort.abort()" in fn(js, "stopReply")
    assert "stopReply()" in js.split('document.addEventListener("keydown", (e) => { if (e.key === "Escape")')[1].split("\n")[0]


def test_a_failed_attempts_words_are_dropped(dash):
    d, _, _ = dash
    _, js, _ = page(d)
    assert 'if (msg.s.stage === "generating") live.text = "";' in fn(js, "streamChat")


def test_regenerate_resends_the_identical_request(dash):
    d, _, _ = dash
    _, js, _ = page(d)
    regen = fn(js, "regenerate")
    assert "sendChat(m.request" in regen and "ui.chatBusy" in regen
    assert "request: payload" in fn(js, "sendChat")


def test_edit_replaces_the_message_and_what_followed(dash):
    d, _, _ = dash
    _, js, _ = page(d)
    assert "ui.convo = ui.convo.slice(0, ui.editIndex)" in fn(js, "submitCommand")


def test_stages_are_shown_as_text_never_as_markup(dash):
    d, _, _ = dash
    _, js, _ = page(d)
    label = fn(js, "stageLabel")
    assert "innerHTML" not in label and "innerHTML" not in fn(js, "renderFeed")
    for stage in ("understanding", "lookup", "context", "generating", "checking"):
        assert f'"{stage}"' in label, stage
    assert "sends its reply in one piece" in label  # honest when a model can't stream


def test_new_controls_meet_touch_and_text_size_rules(dash):
    d, _, _ = dash
    _, _, css = page(d)
    coarse = [b.split("\n}\n")[0] for b in css.split("@media (pointer: coarse), (max-width: 760px)")[1:]]
    assert any(".imode, .btn-xs { min-height: 44px; min-width: 44px; }" in b for b in coarse)
    assert ".cmd .intel-modes[hidden] { display: none; }" in css and ".cmd-actions .btn[hidden] { display: none; }" in css
