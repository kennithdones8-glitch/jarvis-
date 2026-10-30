from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from helpers import build_registry  # noqa: E402

from jarvis.core import Kernel  # noqa: E402

DEFAULT_POLICY = """
[filesystem]
roots = ["{root}"]

[[rules]]
id = "notes-write"
effect = "allow"
tools = ["fs"]
actions = ["write", "append"]
resources = ["{root}/notes/**"]

[[rules]]
id = "net-allow"
effect = "allow"
tools = ["net"]
actions = ["post"]
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "work"
    (r / "notes").mkdir(parents=True)
    return r


@pytest.fixture
def make_kernel(tmp_path: Path, root: Path):
    opened: list[Kernel] = []

    def _make(policy: str | None = DEFAULT_POLICY, registry=None, **kwargs) -> Kernel:
        policy_path = tmp_path / "policy.toml"
        if policy is not None:
            policy_path.write_text(policy.replace("{root}", str(root)))
        kernel = Kernel(tmp_path / "home", policy_path=policy_path, registry=registry or build_registry(), **kwargs)
        opened.append(kernel)
        return kernel

    yield _make
    for k in opened:
        k.close()
