import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GateResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    command: str


def run_gate(
    command: str | Sequence[str],
    cwd: str | Path | None = None,
    timeout: int = 300,
) -> GateResult:
    cmd_str = command if isinstance(command, str) else " ".join(command)

    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=True,
        )

        return GateResult(
            ok=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            command=cmd_str,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else (exc.stdout.decode() if exc.stdout else "")
        )
        stderr = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else (exc.stderr.decode() if exc.stderr else "")
        )
        return GateResult(
            ok=False,
            exit_code=-1,
            stdout=stdout.strip(),
            stderr=f"Command timed out after {timeout} seconds.\n{stderr}".strip(),
            command=cmd_str,
        )
    except Exception as exc:  # noqa: BLE001
        return GateResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr=f"Command failed with exception: {exc!s}".strip(),
            command=cmd_str,
        )


def run_verification_gate(
    story_id: str, cwd: str | Path | None = None, timeout: int = 300
) -> GateResult:
    base_path = Path(cwd) if cwd else Path.cwd()
    test_dir = base_path / "verification" / story_id

    if not test_dir.exists():
        return GateResult(
            ok=False,
            exit_code=1,
            stdout="",
            stderr=f"Verification directory does not exist: {test_dir}",
            command=f"pytest verification/{story_id}",
        )

    cmd = f"pytest -v verification/{story_id}"
    return run_gate(command=cmd, cwd=cwd, timeout=timeout)
