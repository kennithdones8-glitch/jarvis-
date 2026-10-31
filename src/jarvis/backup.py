"""Encrypted backups of JARVIS's state (database: tasks, memory, audit; policy; model config).

Format (.jbak): b"JBAK1" | 16-byte scrypt salt | 12-byte nonce | AES-256-GCM(tar.gz). The tarball
holds a consistent SQLite snapshot (sqlite3 backup API, safe while JARVIS runs), the two config
files and a manifest with SHA-256 of each file. AES-GCM authenticates the data: a tampered or
truncated backup fails to decrypt rather than restoring garbage.

The passphrase is generated once and kept in the macOS Keychain (environment variable fallback for
development). Keep a copy somewhere safe (password manager): without it a backup can't be restored
on a new Mac. Every new backup is immediately test-restored (decrypted, hashes checked, SQLite
integrity_check and audit-chain verification on a temporary copy).

Secrets are not in backups: there are none in JARVIS's files (keys live in the Keychain).
Not included: file-versions/ and trash/ (copies of your own files), claude-workdir/.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import __version__

MAGIC = b"JBAK1"
SECRET_NAME = "backup_passphrase"
KEEP_DEFAULT = 14


class BackupError(RuntimeError):
    pass


# ---- passphrase ------------------------------------------------------------------------------
def _keychain_get() -> str | None:
    if sys.platform != "darwin" or not shutil.which("security"):
        return None
    import subprocess
    p = subprocess.run(["security", "find-generic-password", "-s", "jarvis", "-a", SECRET_NAME, "-w"],
                       capture_output=True, text=True, timeout=10)
    return p.stdout.strip() or None if p.returncode == 0 else None


def _keychain_set(value: str) -> bool:
    if sys.platform != "darwin" or not shutil.which("security"):
        return False
    import subprocess
    # `security -i` reads commands from stdin, so the passphrase never appears in the process list.
    if not re.fullmatch(r"[A-Za-z0-9-]+", value):
        raise BackupError("passphrase contains unsupported characters")
    p = subprocess.run(["security", "-i"], input=f"add-generic-password -U -s jarvis -a {SECRET_NAME} -w {value}\n",
                       capture_output=True, text=True, timeout=10)
    return p.returncode == 0 and "error" not in (p.stdout + p.stderr).lower()


def get_passphrase() -> str | None:
    return os.environ.get("JARVIS_BACKUP_PASSPHRASE") or _keychain_get()


def ensure_passphrase() -> tuple[str, bool]:
    """Return (passphrase, newly_created). Creates and stores one on first use."""
    existing = get_passphrase()
    if existing:
        return existing, False
    words = secrets.token_hex(16)
    phrase = "-".join(words[i:i + 4] for i in range(0, 32, 4))
    if not _keychain_set(phrase):
        raise BackupError("couldn't store a backup passphrase in the Keychain; set JARVIS_BACKUP_PASSPHRASE")
    return phrase, True


def _key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode())


def encrypt(data: bytes, passphrase: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 28:
        raise BackupError("not a JARVIS backup file")
    salt, nonce = blob[5:21], blob[21:33]
    try:
        return AESGCM(_key(passphrase, salt)).decrypt(nonce, blob[33:], MAGIC)
    except InvalidTag:
        raise BackupError("wrong passphrase, or the backup file is damaged") from None


# ---- create / verify / restore ---------------------------------------------------------------
@dataclass(frozen=True)
class BackupResult:
    path: Path
    bytes: int
    verified: bool
    detail: dict[str, Any]
    new_passphrase: str | None = None


def default_dir(home: Path) -> Path:
    return home / "backups"


def _snapshot_db(db_path: Path, dest: Path) -> None:
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(dest)
        with out:
            src.backup(out)
        out.close()
    finally:
        src.close()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_backup(home: Path, policy_path: Path, config_path: Path, *, dest_dir: Path | None = None,
                  keep: int = KEEP_DEFAULT, passphrase: str | None = None) -> BackupResult:
    new_phrase = None
    if passphrase is None:
        passphrase, created = ensure_passphrase()
        new_phrase = passphrase if created else None
    dest_dir = Path(dest_dir) if dest_dir else default_dir(home)
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        files: dict[str, Path] = {}
        _snapshot_db(home / "jarvis.db", tmp_path / "jarvis.db")
        files["jarvis.db"] = tmp_path / "jarvis.db"
        for name, p in (("policy.toml", policy_path), ("jarvis.toml", config_path)):
            if p.exists():
                shutil.copyfile(p, tmp_path / name)
                files[name] = tmp_path / name
        manifest = {"jarvis_version": __version__, "created": time.time(),
                    "files": {name: _sha(p) for name, p in files.items()}}
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name, p in files.items():
                tar.add(p, arcname=name)
            data = json.dumps(manifest, indent=1).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    blob = encrypt(buf.getvalue(), passphrase)
    out = dest_dir / time.strftime("jarvis-%Y%m%d-%H%M%S.jbak")
    if out.exists():
        out = out.with_name(out.stem + f"-{secrets.token_hex(2)}.jbak")
    tmp_out = out.with_suffix(".partial")
    tmp_out.write_bytes(blob)
    os.chmod(tmp_out, 0o600)
    os.replace(tmp_out, out)
    detail = verify_backup(out, passphrase)  # the "restore test": decrypt and check it fully
    prune(dest_dir, keep)
    return BackupResult(out, len(blob), True, detail, new_phrase)


def _open(path: Path, passphrase: str, into: Path) -> dict[str, Any]:
    data = decrypt(Path(path).read_bytes(), passphrase)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = {m.name for m in tar.getmembers()}
        allowed = {"jarvis.db", "policy.toml", "jarvis.toml", "manifest.json"}
        if not names <= allowed or any(not m.isfile() for m in tar.getmembers()):
            raise BackupError("backup contains unexpected entries")
        tar.extractall(into, filter="data")
    manifest = json.loads((into / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        if _sha(into / name) != digest:
            raise BackupError(f"{name} in the backup doesn't match its checksum")
    return manifest


def verify_backup(path: Path, passphrase: str | None = None) -> dict[str, Any]:
    passphrase = passphrase or get_passphrase()
    if not passphrase:
        raise BackupError("no backup passphrase available (Keychain or JARVIS_BACKUP_PASSPHRASE)")
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _open(path, passphrase, Path(tmp))
        conn = sqlite3.connect(Path(tmp) / "jarvis.db")
        try:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("tasks", "memories", "records", "audit")
                      if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (t,)).fetchone()}
        finally:
            conn.close()
        if check != "ok":
            raise BackupError(f"database in the backup failed its integrity check: {check}")
        from .core.audit import AuditLog
        from .core.db import Database
        db = Database(Path(tmp) / "jarvis.db")
        try:
            chain = AuditLog(db).verify()
        finally:
            db.close()
        if not chain.ok:
            raise BackupError(f"audit log in the backup is broken at entry {chain.first_bad_seq}")
    return {"created": manifest["created"], "jarvis_version": manifest["jarvis_version"],
            "files": sorted(manifest["files"]), "counts": counts, "audit_entries": chain.checked}


def restore_backup(path: Path, home: Path, policy_path: Path, config_path: Path, *,
                   passphrase: str | None = None, include_config: bool = True) -> dict[str, Any]:
    """Replace JARVIS's state with a backup. JARVIS must not be running. The current files are kept
    as *.before-restore-<time>. Deletions made since the backup are re-applied (tombstones)."""
    from .core.db import Database
    from .memory import reapply_tombstones

    passphrase = passphrase or get_passphrase()
    if not passphrase:
        raise BackupError("no backup passphrase available (Keychain or JARVIS_BACKUP_PASSPHRASE)")
    db_path = home / "jarvis.db"
    current_tombstones: list[str] = []
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        try:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'tombstones'").fetchone():
                current_tombstones = [r[0] for r in conn.execute("SELECT hash FROM tombstones")]
        finally:
            conn.close()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = _open(path, passphrase, tmp_path)
        verify_backup(path, passphrase)
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                p.rename(Path(f"{db_path}{suffix}.before-restore-{stamp}"))
        shutil.copyfile(tmp_path / "jarvis.db", db_path)
        os.chmod(db_path, 0o600)
        if include_config:
            for name, target in (("policy.toml", policy_path), ("jarvis.toml", config_path)):
                if (tmp_path / name).exists():
                    if target.exists():
                        target.rename(target.with_name(f"{target.name}.before-restore-{stamp}"))
                    shutil.copyfile(tmp_path / name, target)
                    os.chmod(target, 0o600)
    db = Database(db_path)  # also migrates an older backup's schema forward
    try:
        removed = reapply_tombstones(db, current_tombstones)
        from .core.audit import AuditLog
        AuditLog(db).record("backup.restored", actor="user:cli", backup=Path(path).name,
                            backup_created=manifest["created"], reapplied_deletions=removed)
    finally:
        db.close()
    return {"restored_from": str(path), "created": manifest["created"], "reapplied_deletions": removed,
            "previous_files_kept_as": f"*.before-restore-{stamp}"}


def list_backups(dest_dir: Path) -> list[Path]:
    return sorted(Path(dest_dir).glob("jarvis-*.jbak"), reverse=True) if Path(dest_dir).is_dir() else []


def prune(dest_dir: Path, keep: int) -> list[Path]:
    old = list_backups(dest_dir)[keep:]
    for p in old:
        p.unlink(missing_ok=True)
    return old


def last_backup(dest_dir: Path) -> dict[str, Any] | None:
    found = list_backups(dest_dir)
    if not found:
        return None
    return {"path": str(found[0]), "age_hours": round((time.time() - found[0].stat().st_mtime) / 3600, 1),
            "count": len(found)}
