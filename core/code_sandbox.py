"""Isolated code execution: LocalSandbox (measured offline) and E2BSandbox (production).

The boundary rule: `code` is executable input; `data` is DATA and is only ever
written to a JSON file that the code may read. Inbox text must never be
concatenated into `code`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

ALLOWED_IMPORTS = {
    "math", "json", "datetime", "random", "statistics", "re", "collections",
    "itertools", "string", "textwrap", "decimal", "fractions", "socket",
    "time", "typing", "dataclasses", "functools", "operator", "bisect",
    "heapq", "uuid", "enum", "numbers", "zoneinfo",
}
DENIED_IMPORTS = {
    "os", "sys", "subprocess", "pathlib", "importlib", "ctypes", "urllib",
    "requests", "httpx", "http", "ftplib", "smtplib", "telnetlib", "shutil",
    "signal", "resource", "pty", "fcntl", "tempfile", "core", "vault", "app",
    "orchestrator", "capabilities", "pydantic", "sqlmodel", "sqlalchemy",
}
DEFAULT_EGRESS_ALLOWLIST = ("api.telegram.org",)
DEFAULT_TIMEOUT = 10.0
MAX_OUTPUT_CHARS = 20_000


@dataclass(frozen=True)
class SandboxConfig:
    timeout_seconds: float = DEFAULT_TIMEOUT
    egress_allowlist: tuple[str, ...] = DEFAULT_EGRESS_ALLOWLIST
    max_output_chars: int = MAX_OUTPUT_CHARS


@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    output: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_ms: float = 0.0
    error: Optional[str] = None


class SandboxUnavailable(RuntimeError):
    pass


class CodeSandbox(Protocol):
    async def run_code(
        self,
        code: str,
        data: Any = None,
        config: SandboxConfig | None = None,
        secrets: list[str] | None = None,
    ) -> SandboxResult: ...


def redact_secrets(text: str, secrets: list[str] | None) -> str:
    if not secrets:
        return text
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    return text


def _bootstrap(config: SandboxConfig) -> str:
    allowed = sorted(ALLOWED_IMPORTS)
    denied = sorted(DENIED_IMPORTS)
    hosts = list(config.egress_allowlist)
    return f'''
import sys as _sys
_ALLOWED = {allowed!r}
_DENIED = {denied!r}
class _ImportGuard:
    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in _DENIED:
            raise ImportError(f"import denied by sandbox: {{name}}")
        if not root.startswith("_") and root not in _ALLOWED and root != "__future__":
            raise ImportError(f"import denied by sandbox: {{name}}")
        return None
_sys.meta_path.insert(0, _ImportGuard())
import socket as _socket
_ALLOWED_HOSTS = {hosts!r}
_orig_connect = _socket.socket.connect
def _guarded_connect(self, address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else str(address)
    if host not in _ALLOWED_HOSTS:
        raise PermissionError(f"egress denied: {{host}}")
    return _orig_connect(self, address, *args, **kwargs)
_socket.socket.connect = _guarded_connect
_orig_create = _socket.create_connection
def _guarded_create(address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else str(address)
    if host not in _ALLOWED_HOSTS:
        raise PermissionError(f"egress denied: {{host}}")
    return _orig_create(address, *args, **kwargs)
_socket.create_connection = _guarded_create
import builtins as _b
_orig_open = _b.open
def _guarded_open(file, mode="r", *args, **kwargs):
    if isinstance(file, str) and (file.startswith("/") or ".." in file.split("/")):
        raise PermissionError(f"filesystem denied: {{file}}")
    return _orig_open(file, mode, *args, **kwargs)
_b.open = _guarded_open
import json as _json
def _load_data():
    try:
        with open("data.json", encoding="utf-8") as _f:
            return _json.load(_f)
    except Exception:
        return None
data = _load_data()
'''


class LocalSandbox:
    """Process-isolated sandbox used for offline measurement."""

    def __init__(self) -> None:
        self.provider = "local"

    async def run_code(
        self,
        code: str,
        data: Any = None,
        config: SandboxConfig | None = None,
        secrets: list[str] | None = None,
    ) -> SandboxResult:
        config = config or SandboxConfig()
        workdir = Path(tempfile.mkdtemp(prefix="nexus-sandbox-"))
        started = time.monotonic()
        try:
            (workdir / "data.json").write_text(json.dumps(data), encoding="utf-8")
            runner = workdir / "runner.py"
            runner.write_text(_bootstrap(config) + "\n" + code, encoding="utf-8")
            env = {"PATH": "/usr/bin:/bin"}
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(runner),
                cwd=str(workdir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=config.timeout_seconds
                )
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                stdout, stderr = await proc.communicate()
                timed_out = True
            duration_ms = (time.monotonic() - started) * 1000
            output = stdout.decode("utf-8", "replace")[: config.max_output_chars]
            err = stderr.decode("utf-8", "replace")[: config.max_output_chars]
            output = redact_secrets(output, secrets)
            err = redact_secrets(err, secrets)
            ok = (proc.returncode == 0) and not timed_out
            return SandboxResult(
                ok=ok,
                output=output,
                stderr=err,
                timed_out=timed_out,
                duration_ms=round(duration_ms, 2),
                error=None if ok else (err or "exit code %s" % proc.returncode),
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


class E2BSandbox:
    """E2B provider (production default when E2B_API_KEY is set).

    Unverified — assumption: the real E2B execution path cannot be exercised in
    this environment (no e2b package / no API key). Provider selection and the
    offline contract are covered by tests.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.provider = "e2b"
        self.api_key = api_key or os.environ.get("E2B_API_KEY") or ""

    async def run_code(
        self,
        code: str,
        data: Any = None,
        config: SandboxConfig | None = None,
        secrets: list[str] | None = None,
    ) -> SandboxResult:
        if not self.api_key:
            raise SandboxUnavailable("E2B_API_KEY is not set")
        try:
            from e2b import Sandbox  # type: ignore
        except ImportError as exc:
            raise SandboxUnavailable("e2b package is not installed") from exc
        # Not exercised offline; kept behind the key check so it cannot run
        # accidentally with fake credentials.
        raise SandboxUnavailable("E2B execution is not available in this environment")


def get_sandbox() -> CodeSandbox:
    if os.environ.get("E2B_API_KEY"):
        return E2BSandbox()
    return LocalSandbox()
