"""What's new: the newest CHANGELOG section's headings appear after an update until dismissed; a fresh install
sees nothing "new"; only a fingerprint is stored."""

from jarvis import whatsnew
from jarvis.core import Kernel


def _repo(tmp_path, heads):
    r = tmp_path / "repo"
    r.mkdir(exist_ok=True)
    body = "\n".join(f"### {h}\n\n- detail\n" for h in heads)
    (r / "CHANGELOG.md").write_text(f"# Changelog\n\n## Unreleased\n\n{body}\n## 0.1.0\n\n### Old thing\n")
    return r


def test_new_items_show_once_after_an_update(tmp_path):
    k = Kernel(tmp_path / "home")
    try:
        r = _repo(tmp_path, ["Chess", "Objectives"])
        assert whatsnew.items(r) == ["Chess", "Objectives"]
        assert whatsnew.state(k, r)["unseen"] is False           # a fresh install: nothing is "new"
        r = _repo(tmp_path, ["Checkers", "Chess", "Objectives"])  # an update brings a new section heading
        st = whatsnew.state(k, r)
        assert st["unseen"] is True and st["items"][0] == "Checkers"
        whatsnew.mark_seen(k, r)
        assert whatsnew.state(k, r)["unseen"] is False
        assert len(k.db.one("SELECT value FROM meta WHERE key = ?", (whatsnew.SEEN,))["value"]) == 16
    finally:
        k.close()


def test_no_changelog_means_nothing_to_show(tmp_path):
    assert whatsnew.items(tmp_path / "nowhere") == []
