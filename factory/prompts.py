"""Role Prompt Builders for Dev and QA Agents in the Software Factory.

Why: Prompts set clear operational boundaries and responsibilities for each agent role,
reinforcing write isolation and providing feedback context during repair loops.
"""

from typing import Any


def build_dev_prompt(
    story_id: str,
    story_content: str,
    failure_report: dict[str, Any] | None = None,
) -> str:
    """Construct the instruction prompt for the Dev agent.

    Why: Instructs Dev to implement application code and unit tests while enforcing
    read-only access to verification suites. On retries, it includes the failure report.
    """
    prompt = f"""# Role: Software Developer
You are the implementation developer for story `{story_id}`.

## Story Specification:
{story_content}

## Instructions:
1. Review the story specification and existing codebase before writing code.
2. Implement the required features under `src/` and unit/integration tests under `tests/`.
3. Run local checks (linter, unit tests) to ensure your implementation works cleanly.

## Strict Invariants & Constraints:
- NEVER modify or delete any files in `verification/**`. You have READ-ONLY access to verification.
- Do NOT claim completion if any tests or commands fail.
"""

    # If this is a repair attempt, append the structured failure report
    if failure_report:
        gate_name = failure_report.get("gate", "unknown")
        exit_code = failure_report.get("exit_code", -1)
        stderr_tail = failure_report.get("stderr_tail", "No stderr output")

        prompt += f"""
## Previous Attempt Failure Report:
The previous run failed at gate `{gate_name}` with exit code `{exit_code}`.

Error details:
```
{stderr_tail}
```

Please fix the implementation based on these error details.
"""

    return prompt.strip()


def build_qa_prompt(
    story_id: str,
    story_content: str,
) -> str:
    """Construct the instruction prompt for the independent QA agent.

    Why: Instructs QA to independently author verification tests under verification/{story_id}/
    without modifying application source code.
    """
    return f"""# Role: Independent QA Engineer
You are the independent QA verification engineer for story `{story_id}`.

## Story Specification:
{story_content}

## Instructions:
1. Carefully review the acceptance criteria and constraints in the story specification above.
2. Inspect the current codebase to understand how the feature is implemented.
3. Write comprehensive, executable verification tests strictly under `verification/{story_id}/`.
4. Ensure the tests independently verify every acceptance criterion.

## Strict Invariants & Constraints:
- You must write ALL verification tests strictly inside `verification/{story_id}/`.
- NEVER modify application source code in `src/` or developer tests in `tests/`.
- NEVER weaken or alter acceptance criteria to match failing implementation behavior.
- Ensure all tests are self-contained and executable via pytest (e.g., `pytest verification/{story_id}`).
""".strip()
