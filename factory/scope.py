import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class ScopeResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    diff: str = ""


def get_changed_files(cwd: str | Path = ".") -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )

    files: list[str] = []

    for line in proc.stdout.splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue

        parts = trimmed.split(maxsplit=1)
        if len(parts) == 2:
            raw_path = parts[1].strip().strip('"')

            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ")[1].strip().strip('"')

            normalized = raw_path.replace("\\", "/")
            files.append(normalized)

    return files


def get_git_diff(cwd: str | Path = ".", files: list[str] | None = None) -> str:
    cmd = ["git", "diff", "HEAD"]
    if files:
        cmd.extend(["--", *files])

    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )

    return proc.stdout


FRAMEWORK_PREFIXES = (
    "factory/",
    ".factory/",
    ".agents/",
    ".gemini/",
    ".vscode/",
    "docs/",
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
    "langgraph.json",
)


def check_scope(
    role: Literal["dev", "qa"],
    changed_files: list[str],
    story_id: str,
) -> list[str]:
    violations: list[str] = []
    qa_prefix = f"verification/{story_id}/"

    for path in changed_files:
        # Ignore changes to the orchestration factory framework itself
        if any(path == prefix or path.startswith(prefix) for prefix in FRAMEWORK_PREFIXES):
            continue

        if role == "dev":
            if path.startswith("verification/") or path == "verification":
                violations.append(path)
        elif role == "qa" and not path.startswith(qa_prefix):
            violations.append(path)

    return violations


def revert_violations(cwd: str | Path, violations: list[str]) -> None:
    if not violations:
        return

    subprocess.run(
        ["git", "restore", "--staged", "--worktree", "--", *violations],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )

    subprocess.run(
        ["git", "clean", "-f", "--", *violations],
        cwd=str(cwd),
        capture_output=True,
        check=False,
    )


def enforce_scope(
    role: Literal["dev", "qa"],
    story_id: str,
    cwd: str | Path = ".",
    auto_revert: bool = True,
) -> ScopeResult:

    changed = get_changed_files(cwd=cwd)
    violations = check_scope(role=role, changed_files=changed, story_id=story_id)
    if not violations:
        return ScopeResult(ok=True, changed_files=changed)

    diff = get_git_diff(cwd=cwd, files=violations)
    if auto_revert:
        revert_violations(cwd=cwd, violations=violations)
    return ScopeResult(
        ok=False,
        violations=violations,
        changed_files=changed,
        diff=diff,
    )
