#!/usr/bin/env python3
"""One explicit JDK25/official JUnit runner for host and /grade jobs."""

import os
from pathlib import Path
import selectors
import signal
import subprocess  # nosec B404 # subprocess is the intentional argv process boundary; no shell import shortcut
import time
from collections.abc import Sequence
from typing import Literal

__all__ = ["GraderError", "_protect_input_identity", "_run"]

OUTPUT_LIMIT = 65536


class GraderError(Exception):
    """An operator/configuration failure, never a wrong student answer."""


def _protect_input_identity(job: Path) -> None:
    # Bind mounts retain host owners. chmod(0700) alone is ineffective when a
    # host owner has the same numeric UID as the official container's sbuser.
    # Remap only the container account; never chown the caller's mounted tree.
    import pwd

    owners = {path.stat().st_uid for path in (job, job / "student", job / "tests")}
    if pwd.getpwnam("sbuser").pw_uid not in owners:
        return
    if not Path("/.dockerenv").is_file():
        raise GraderError(
            "Sandbox UID remapping requires the supported Docker container"
        )
    allocated = {entry.pw_uid for entry in pwd.getpwall()}
    candidate = next(
        (uid for uid in range(60000, 60100) if uid not in owners | allocated), None
    )
    if candidate is None:
        raise GraderError("No isolated sandbox UID is available")
    code, _text, reason = _run(["usermod", "--uid", str(candidate), "sbuser"], job, 5)
    if code or reason or pwd.getpwnam("sbuser").pw_uid in owners:
        raise GraderError("Cannot isolate sandbox UID from mounted input owners")


def _run(
    command: Sequence[str], cwd: Path, timeout: float, output_limit: int = OUTPUT_LIMIT
) -> tuple[int, str, Literal["timeout", "output_limit"] | None]:
    try:
        process = subprocess.Popen(  # nosec B603 # explicit argv sequence is passed without shell; execution belongs to this component
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise GraderError("Required grading executable is unavailable") from exc
    if process.stdout is None:
        raise GraderError("Required grading output pipe is unavailable")
    output = bytearray()
    reason: Literal["timeout", "output_limit"] | None = None
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    room = output_limit - len(output)
                    output.extend(chunk[:room])
                    if len(chunk) > room:
                        reason = "output_limit"
                        break
                if reason:
                    break
            if reason is None:
                try:
                    process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    reason = "timeout"
    finally:
        # Clean up children too, including processes retaining a stdout handle.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        returncode = process.wait()
        process.stdout.close()
    text = bytes(output).decode("utf-8", errors="replace")
    text = text.encode("utf-8")[:output_limit].decode("utf-8", errors="ignore")
    return returncode, text, reason
