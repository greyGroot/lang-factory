import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

@dataclass
class GateResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    command: str
    
def run_gate(
    command: Union[str, Sequence[str]],
    cwd: Union[str, Path, None] = None,
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
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode() if exc.stdout else "")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode() if exc.stderr else "")
        return GateResult(
            ok=False,
            exit_code=-1,
            stdout=stdout.strip(),
            stderr=f"Command timed out after {timeout} seconds.\n{stderr}".strip(),
            command=cmd_str,
        )
    except Exception as exc:
        return GateResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr=f"Command failed with exception: {str(exc)}".strip(),
            command=cmd_str,
        )