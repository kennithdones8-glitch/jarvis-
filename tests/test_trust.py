"""The Trust Contract is generated from what JARVIS enforces, so it can't drift from it."""

import json

import pytest
from test_dashboard import call

from jarvis.core.permissions import Effect, ResourceKind
from jarvis.gate import SECURITY
from jarvis.trust import BUILT_IN_NEVER, PHRASES, SAMPLE, contract


def texts(lines):
    return " | ".join(ln.text for ln in lines)


def test_every_line_agrees_with_the_permission_engine(make_kernel, root):
    """Re-ask the engine about every action and check it's in the right section, worded the right way."""
    k = make_kernel(registry="default")
    c = contract(k)
    own, asks, never = texts(c.on_its_own), texts(c.asks_first), texts(c.never)
    for tool in k.registry.names():
        for action, a in k.registry.get(tool).actions.items():
            phrase = PHRASES.get((tool, action), f"{tool}.{action}")
            phrase = phrase[0].upper() + phrase[1:]
            res = str(root / SAMPLE) if a.resource_kind is ResourceKind.PATH else (
                "https://example.com/" if a.resource_kind is ResourceKind.URL else None)
            d = k.permissions.evaluate(tool=tool, action=action, tier=a.tier, resource_kind=a.resource_kind, resource=res)
            section = {Effect.ALLOW: own, Effect.CONFIRM: asks, Effect.DENY: never}[d.effect]
            assert phrase in section, f"{tool}.{action} should be under {d.effect}"


def test_a_policy_change_shows_up(make_kernel):
    k = make_kernel(registry="default")
    assert "Move or rename files" in texts(contract(k).asks_first)
    k2 = make_kernel(registry="default", policy='[filesystem]\nroots = ["{root}"]\n\n[[rules]]\nid = "tidy"\n'
                     'effect = "allow"\ntools = ["fs"]\nactions = ["move"]\n\n[[rules]]\nid = "no-writes"\n'
                     'effect = "deny"\ntools = ["fs"]\nactions = ["write"]\n')
    c = contract(k2)
    assert "Move or rename files" in texts(c.on_its_own) and "Move or rename files" not in texts(c.asks_first)
    assert "Write or change files" in texts(c.never) and "“no-writes”" in texts(c.never)


def test_high_stakes_actions_are_never_listed_as_done_on_its_own(make_kernel):
    assert "Delete files" not in texts(contract(make_kernel(registry="default")).on_its_own)
    # even an "allow everything" rule can't make deletes silent
    c = contract(make_kernel(registry="default", policy='[filesystem]\nroots = ["{root}"]\n\n[[rules]]\nid = "yolo"\n'
                             'effect = "allow"\ntools = ["*"]\nactions = ["*"]\n'))
    assert "Delete files" in texts(c.asks_first) and "Delete files" not in texts(c.on_its_own)


def test_built_in_promises_are_backed_by_release_gate_items():
    for text, item in BUILT_IN_NEVER:
        assert item in SECURITY or item == "Policy (propose-only)", f"no gate item proves: {text}"


def test_budget_and_phone_lines(make_kernel):
    k = make_kernel(registry="default")
    c = contract(k)
    assert "Spends nothing: the monthly budget is $0" in texts(c.privacy)
    assert "Phone access is off" in texts(c.phone)


def test_cloud_consent_and_a_standing_grant(make_kernel, tmp_path):
    cfg = tmp_path / "claude.toml"
    cfg.write_text('[privacy]\nlocal_only_categories = ["screenshot"]\n\n[providers.claude]\nkind = "claude_code"\n'
                   'enabled = true\n\n[[providers.claude.models]]\nid = "sonnet"\ncapabilities = ["chat"]\n'
                   'context_tokens = 200000\nquality = 5\nspeed = 3\n')
    k = make_kernel(registry="default", config_path=cfg)
    p = texts(contract(k).privacy)
    assert "Asks you each time before sending to claude: your files and app data" in p
    assert "Never leaves this Mac: screenshots" in p
    k.models.router.gate.grants.grant(category="memory", provider="claude", by="user:test")
    p = texts(contract(k).privacy)
    assert "May be sent to claude without asking: what JARVIS remembers about you" in p


def test_command_and_page(dash):
    d, _, _ = dash
    status, headers, body = call(d, "/api/trust")
    c = json.loads(body)
    assert status == 200 and {"on_its_own", "asks_first", "never", "privacy", "phone"} <= set(c)
    assert call(d, "/api/trust", cookie=False)[0] in (401, 403)
    status, headers, body = call(d, "/trust")
    assert status == 200 and b"/static/trust.js" in body and b"style=" not in body
    js = call(d, "/static/trust.js")[2].decode()
    assert "innerHTML" not in js
    assert b'href="/trust"' in call(d, "/")[2]


@pytest.mark.parametrize("flag", [[], ["--json"]])
def test_cli(tmp_path, capsys, flag):
    from jarvis.cli import main as cli_main
    home = tmp_path / "h"
    assert cli_main(["--home", str(home), "init"]) == 0
    capsys.readouterr()
    assert cli_main(["--home", str(home), "trust", *flag]) == 0
    out = capsys.readouterr().out
    assert ("NEVER DOES" in out) if not flag else ("never" in json.loads(out))
