import os

import pytest

from jarvis.core.permissions import Effect, PermissionEngine, Policy, PolicyError, ResourceKind, Tier

PATH = ResourceKind.PATH


def engine(root, rules=(), protected=()):
    return PermissionEngine(Policy.from_dict({"filesystem": {"roots": [str(root)]}, "rules": list(rules)},
                                             protected=protected))


def ev(e, tool="fs", action="write", tier=Tier.ROUTINE, kind=PATH, resource=None):
    return e.evaluate(tool=tool, action=action, tier=tier, resource_kind=kind, resource=resource)


def test_outside_root_denied(root, tmp_path):
    d = ev(engine(root), tier=Tier.READ, resource=str(tmp_path / "elsewhere.txt"))
    assert d.effect is Effect.DENY and "outside" in d.reason


def test_path_traversal_denied(root):
    d = ev(engine(root), tier=Tier.READ, resource=f"{root}/notes/../../escape.txt")
    assert d.effect is Effect.DENY


def test_symlink_escape_denied(root, tmp_path):
    secret = tmp_path / "secret"
    secret.mkdir()
    os.symlink(secret, root / "link")
    d = ev(engine(root), tier=Tier.READ, resource=f"{root}/link/file.txt")
    assert d.effect is Effect.DENY


def test_invalid_paths_denied(root):
    e = engine(root)
    for bad in ("", "   ", f"{root}/a\x00b", None, 42):
        assert ev(e, resource=bad).effect is Effect.DENY


def test_read_inside_root_allowed_by_default(root):
    assert ev(engine(root), tier=Tier.READ, resource=f"{root}/a.txt").effect is Effect.ALLOW


def test_write_without_rule_requires_confirmation(root):
    assert ev(engine(root), resource=f"{root}/a.txt").effect is Effect.CONFIRM


def test_allow_rule_scoped_to_subtree(root):
    e = engine(root, [{"id": "n", "effect": "allow", "tools": ["fs"], "actions": ["write"],
                       "resources": [f"{root}/notes/**"]}])
    assert ev(e, resource=f"{root}/notes/x.md").effect is Effect.ALLOW
    assert ev(e, resource=f"{root}/other/x.md").effect is Effect.CONFIRM


def test_deny_beats_allow(root):
    e = engine(root, [{"id": "a", "effect": "allow"}, {"id": "d", "effect": "deny", "actions": ["write"]}])
    d = ev(e, resource=f"{root}/x")
    assert d.effect is Effect.DENY and d.rule_id == "d"


@pytest.mark.parametrize("tier", [Tier.EXTERNAL, Tier.HIGH_RISK])
def test_high_tiers_never_auto_allowed(root, tier):
    e = engine(root, [{"id": "everything", "effect": "allow"}])
    assert ev(e, tier=tier, resource=f"{root}/x").effect is Effect.CONFIRM


def test_protected_paths_not_writable_but_readable(root):
    e = engine(root, [{"id": "a", "effect": "allow"}], protected=[root / "notes"])
    assert ev(e, resource=f"{root}/notes/x").effect is Effect.DENY
    assert ev(e, tier=Tier.READ, resource=f"{root}/notes/x").effect is Effect.ALLOW


def test_url_scheme_enforced(root):
    e = engine(root)
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://x.org/", "https://", 5):
        assert ev(e, tool="web", action="get", tier=Tier.READ, kind=ResourceKind.URL, resource=bad).effect is Effect.DENY
    ok = ev(e, tool="web", action="get", tier=Tier.READ, kind=ResourceKind.URL, resource="https://example.org/a")
    assert ok.effect is Effect.ALLOW


@pytest.mark.parametrize("bad", [
    {"surprise": {}},
    {"filesystem": {"rootz": []}},
    {"rules": [{"id": "x", "effect": "maybe"}]},
    {"rules": [{"id": "x", "effect": "allow"}, {"id": "x", "effect": "deny"}]},
    {"rules": [{"effect": "allow"}]},
    {"rules": [{"id": "x", "effect": "allow", "tool": ["fs"]}]},
])
def test_invalid_policies_rejected(bad):
    with pytest.raises(PolicyError):
        Policy.from_dict(bad)
