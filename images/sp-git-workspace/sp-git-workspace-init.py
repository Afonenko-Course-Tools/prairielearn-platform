"""Проверка seed и атомарное создание work; restart сохраняет работу студента."""

import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess  # nosec B404 # subprocess is the intentional argv process boundary; no shell import shortcut
import tempfile
from typing import TypeGuard, TypedDict
import zipfile


class Identity(TypedDict):
    schema: str
    seedCommit: str


def _object(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def initialize(root: Path) -> None:
    seed = root / ".pl-seed"
    raw: object = json.loads((seed / "manifest.json").read_text())
    if (
        not _object(raw)
        or set(raw) != {"schema", "files"}
        or raw["schema"] != "pl-git-workspace-seed-v1"
    ):
        raise SystemExit("SP.SEED_INVALID: неверный manifest")
    archive = seed / "starter.zip"
    work = root / "work"
    identity = seed / "identity.json"
    if work.exists() or work.is_symlink():
        if work.is_symlink() or not work.is_dir() or not identity.is_file():
            raise SystemExit(
                "SP.RESUME_UNKNOWN: работа сохранена; автоматическая инициализация запрещена"
            )
        json.loads(identity.read_text())
        # На restart не вызываем даже Git: чтение status может освежить index.
        return
    if identity.exists():
        raise SystemExit(
            "SP.RESUME_MISSING: выбранная работа отсутствует; автоматический сброс запрещён"
        )
    entries = raw["files"]
    if not _list(entries) or not 1 <= len(entries) <= 4096:
        raise SystemExit("SP.SEED_INVALID: неверный inventory")
    expected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str):
            raise SystemExit("SP.SEED_INVALID: неверный inventory")
        expected.add(entry)
    if len(expected) != len(entries):
        raise SystemExit("SP.SEED_INVALID: повтор inventory")
    stage = Path(tempfile.mkdtemp(prefix=".sp-init-", dir=root))
    try:
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if (
                len(members) != len(expected)
                or sum(m.file_size for m in members) > 16 * 1024 * 1024
            ):
                raise SystemExit("SP.SEED_INVALID: состав или размер ZIP")
            seen: set[str] = set()
            for member in members:
                name = member.filename
                parts = PurePosixPath(name).parts
                mode = member.external_attr >> 16
                if (
                    name not in expected
                    or name in seen
                    or not parts
                    or name.startswith("/")
                    or "\\" in name
                    or "\x00" in name
                    or any(p in ("", ".", "..") for p in name.split("/"))
                    or parts[0] == ".pl-seed"
                    or member.is_dir()
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                ):
                    raise SystemExit("SP.SEED_INVALID: небезопасный member")
                seen.add(name)
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(member))
                target.chmod(0o755 if mode & 0o111 else 0o644)
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL="/dev/null",
            GIT_TERMINAL_PROMPT="0",
        )

        def git(*args: str) -> str:
            return subprocess.check_output(  # nosec B603, B607 # explicit argv sequence is passed without shell; execution belongs to this component; system tools are intentionally resolved through the operator-controlled PATH (AGENTS.md)
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    *args,
                ],
                cwd=stage / "work",
                env=env,
                text=True,
                stderr=subprocess.PIPE,
            ).strip()

        git("fsck", "--full", "--no-reflogs")
        if (
            git("symbolic-ref", "HEAD") != "refs/heads/main"
            or git("rev-list", "--count", "--all") != "1"
            or git("status", "--porcelain") != ""
        ):
            raise SystemExit("SP.SEED_INVALID: требуется только чистый исходный A/main")
        # В seed допустимо только замыкание A: --all не видит недостижимое решение.
        initial_objects = set(
            git("rev-list", "--objects", "--no-object-names", "HEAD").splitlines()
        )
        stored_objects = set(
            git(
                "cat-file", "--batch-all-objects", "--batch-check=%(objectname)"
            ).splitlines()
        )
        if stored_objects != initial_objects:
            raise SystemExit(
                "SP.SEED_INVALID: object database содержит объекты вне исходного A"
            )
        chosen = Identity(
            schema="pl-git-workspace-seed-v1", seedCommit=git("rev-parse", "HEAD")
        )
        # Публикуем проверенный work одним rename, существующую работу не перезаписываем.
        (stage / "work").rename(work)
        for source in stage.iterdir():
            target = root / source.name
            if not target.exists():
                source.rename(target)
        pending = seed / "identity.json.pending"
        pending.write_text(json.dumps(chosen, ensure_ascii=False, indent=2) + "\n")
        pending.replace(identity)
    finally:
        shutil.rmtree(stage)


if __name__ == "__main__":
    initialize(Path.cwd())
