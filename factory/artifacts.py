"""Artifact management and structured failure reporting for factory runs."""

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factory.gates import GateResult


def generate_run_id() -> str:
    """Generate a UTC timestamped run ID (e.g., 20260927-200425)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def init_run_dir(
    story_id: str,
    run_id: str | None = None,
    base_dir: str | Path = ".factory/runs",
) -> Path:
    """Initialize standard run directory tree:
    .factory/runs/{story_id}/{run_id}/
    ├── dev/
    └── qa/
    """
    actual_run_id = run_id or generate_run_id()
    run_dir = Path(base_dir) / story_id / actual_run_id

    # Create run root and role subdirectories (recursive mkdir)
    (run_dir / "dev").mkdir(parents=True, exist_ok=True)
    (run_dir / "qa").mkdir(parents=True, exist_ok=True)

    return run_dir


def create_failure_report(
    gate_name: str,
    result: GateResult,
    failed_tests: list[str] | None = None,
    max_stderr_lines: int = 25,
) -> dict[str, Any]:
    """Create a structured, machine-readable failure report for repair prompts."""
    stderr_lines = result.stderr.strip().splitlines()
    stderr_tail = "\n".join(stderr_lines[-max_stderr_lines:]) if stderr_lines else ""

    return {
        "gate": gate_name,
        "exit_code": result.exit_code,
        "failed_tests": failed_tests or [],
        "command": result.command,
        "stderr_tail": stderr_tail,
        "stdout": result.stdout,
    }


def save_gate_result(
    run_dir: str | Path,
    gate_name: str,
    result: GateResult,
) -> Path:
    """Persist raw GateResult as <gate_name>.json in the run directory."""
    target_path = Path(run_dir) / f"{gate_name}.json"
    data = asdict(result)
    target_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return target_path


def save_failure_report(
    run_dir: str | Path,
    gate_name: str,
    result: GateResult,
    failed_tests: list[str] | None = None,
) -> Path:
    """Persist structured failure report as <gate_name>-failure.json."""
    target_path = Path(run_dir) / f"{gate_name}-failure.json"
    report = create_failure_report(gate_name, result, failed_tests=failed_tests)
    target_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return target_path
