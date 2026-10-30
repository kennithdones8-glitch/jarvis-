import sqlite3

import pytest

from jarvis.core.redact import REDACTED, redact


def test_chain_verifies(make_kernel):
    k = make_kernel()
    for i in range(5):
        k.audit.record("test.event", n=i)
    result = k.audit.verify()
    assert result.ok and result.checked == 5


def test_update_and_delete_blocked_by_triggers(make_kernel):
    k = make_kernel()
    k.audit.record("test.event", n=1)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with k.db.tx() as c:
            c.execute("UPDATE audit SET event = 'forged'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with k.db.tx() as c:
            c.execute("DELETE FROM audit")


def test_tampering_detected_even_if_triggers_removed(make_kernel):
    k = make_kernel()
    for i in range(3):
        k.audit.record("test.event", n=i)
    with k.db.tx() as c:
        c.execute("DROP TRIGGER audit_append_only_update")
        c.execute("UPDATE audit SET payload = '{\"n\":99}' WHERE seq = 2")
    result = k.audit.verify()
    assert not result.ok and result.first_bad_seq == 2


def test_deleted_middle_entry_detected(make_kernel):
    k = make_kernel()
    for i in range(3):
        k.audit.record("test.event", n=i)
    with k.db.tx() as c:
        c.execute("DROP TRIGGER audit_append_only_delete")
        c.execute("DELETE FROM audit WHERE seq = 2")
    assert not k.audit.verify().ok


def test_secrets_redacted_in_audit(make_kernel):
    k = make_kernel()
    k.audit.record("test.event", api_key="sk-ant-abcdefghijklmnop123", note="token ghp_" + "a" * 36,
                   tokens_used=12)
    payload = k.audit.entries()[-1]["payload"]
    assert payload["api_key"] == REDACTED
    assert "ghp_" not in payload["note"]
    assert payload["tokens_used"] == 12  # not a secret just because it contains "token"


def test_redact_nested_and_patterns():
    out = redact({"headers": {"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz"},
                  "items": ["AKIAABCDEFGHIJKLMNOP", "fine"],
                  "pem": "-----BEGIN RSA PRIVATE KEY-----\nxyz\n-----END RSA PRIVATE KEY-----"})
    assert out["headers"]["Authorization"] == REDACTED
    assert out["items"] == [REDACTED, "fine"]
    assert out["pem"] == REDACTED
