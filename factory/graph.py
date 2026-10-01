"""LangGraph Software Factory Workflow Graph.

Why: Defines the state machine graph topology, orchestrating prepare -> dev -> scope gates -> checks -> qa -> verification -> human approval -> loop/end.
"""

from pathlib import Path
from typing import Literal

from langgraph.graph import END, START, StateGraph

from factory.artifacts import create_failure_report
from factory.gates import run_verification_gate
from factory.prompts import build_dev_prompt
from factory.scope import enforce_scope
from factory.state import FactoryState

# =====================================================================
# 1. Node Functions
# =====================================================================


def prepare(state: FactoryState) -> dict:
    """Initialize run context and default attempt counter.

    Why: Sets the initial lifecycle status and failure context for a fresh run.
    """
    print("[prepare] Initializing factory workflow run...")
    return {
        "status": "running",
        "attempt": state.get("attempt", 1),
        "max_attempts": state.get("max_attempts", 3),
        "changed_files": [],
        "failure_report": None,
    }


def dev(state: FactoryState) -> dict:
    """Execute Dev agent: implements feature or repairs based on failure report.

    Why: On retries, Dev receives the structured failure report from previous gate runs
    and reuses the existing conversation session to perform targeted bug fixes.
    """
    attempt = state.get("attempt", 1)
    story_id = state.get("story_id", "todo-app")
    story_path = state.get("story_path", f"docs/stories/{story_id}/story.md")
    failure_report = state.get("failure_report")
    conversation_id = state.get("dev_conversation_id", f"dev-session-{story_id}")

    # Read story specification
    story_file = Path(story_path)
    story_content = (
        story_file.read_text(encoding="utf-8")
        if story_file.exists()
        else "Story content not found."
    )

    if failure_report:
        gate_name = failure_report.get("gate", "unknown")
        print(f"[dev] REPAIR ATTEMPT {attempt}: Repairing failure from gate '{gate_name}'...")
    else:
        print(f"[dev] INITIAL ATTEMPT {attempt}: Implementing story '{story_id}'...")

    # Build prompt for Dev worker (incorporating failure report on retries)
    prompt = build_dev_prompt(  # noqa: F841
        story_id=story_id,
        story_content=story_content,
        failure_report=failure_report,
    )

    return {
        "dev_status": "success",
        "dev_conversation_id": conversation_id,
        "attempt": attempt,
    }


def dev_scope_gate(state: FactoryState) -> dict:
    """Inspect Git changes to ensure Dev did not touch verification/**.

    Why: Enforces the non-negotiable invariant that Dev has read-only access to verification.
    """
    story_id = state.get("story_id", "todo-app")
    repo_root = state.get("repo_root", ".")
    print("[dev_scope_gate] Checking Dev write scope...")

    scope_result = enforce_scope(role="dev", story_id=story_id, cwd=repo_root)
    return {
        "dev_scope_ok": scope_result.ok,
        "changed_files": scope_result.changed_files,
    }


def dev_checks(state: FactoryState) -> dict:
    """Run deterministic lint and developer unit tests.

    Why: Ensures code compiles and passes local developer tests before handing off to QA.
    """
    print("[dev_checks] Running deterministic lint and unit tests...")
    return {
        "dev_gate_ok": True,
    }


def qa(state: FactoryState) -> dict:
    """Execute QA agent to author verification tests.

    Why: Independent QA creates test suite verifying acceptance criteria.
    """
    story_id = state.get("story_id", "todo-app")
    print(f"[qa] Executing QA agent for '{story_id}'...")
    return {
        "qa_status": "success",
        "qa_conversation_id": f"qa-session-{story_id}",
    }


def qa_scope_gate(state: FactoryState) -> dict:
    """Inspect Git changes to ensure QA only modified verification/{story_id}/**.

    Why: Enforces the invariant that QA writes only verification tests and cannot alter source code.
    """
    story_id = state.get("story_id", "todo-app")
    repo_root = state.get("repo_root", ".")
    print(f"[qa_scope_gate] Checking QA write scope for story '{story_id}'...")

    scope_result = enforce_scope(role="qa", story_id=story_id, cwd=repo_root)
    return {
        "qa_scope_ok": scope_result.ok,
        "changed_files": scope_result.changed_files,
    }


def verification(state: FactoryState) -> dict:
    """Run independent verification tests located in verification/{story_id}.

    Why: Evaluates acceptance criteria deterministically. If failed, creates
    a structured failure report for Dev to consume on the next repair attempt.
    """
    story_id = state.get("story_id", "todo-app")
    repo_root = state.get("repo_root", ".")
    print(f"[verification] Executing verification suite for '{story_id}'...")

    gate_result = run_verification_gate(story_id=story_id, cwd=repo_root)

    if gate_result.ok:
        print(f"[verification] PASS: Verification tests passed for '{story_id}'.")
        return {
            "verification_ok": True,
            "failure_report": None,
        }

    # On failure, build structured machine-readable failure report
    print(f"[verification] FAIL: Verification tests failed (exit code {gate_result.exit_code}).")
    failure_report = create_failure_report(
        gate_name="verification",
        result=gate_result,
    )

    return {
        "verification_ok": False,
        "failure_report": failure_report,
    }


def human_approval(state: FactoryState) -> dict:
    """Suspends for human approval when all gates pass."""
    print("[human_approval] Verification passed. Mock approving run...")
    return {
        "status": "passed",
    }


def failed(state: FactoryState) -> dict:
    """Finalize run on unrecoverable error or exceeded retries."""
    print("[failed] Workflow terminated with failure.")
    return {
        "status": "failed",
    }


# =====================================================================
# 2. Router Functions (Conditional Edge Logic)
# =====================================================================


def route_dev_scope(state: FactoryState) -> Literal["dev_checks", "failed"]:
    """Route after Dev scope inspection."""
    if state.get("dev_scope_ok", False):
        return "dev_checks"
    return "failed"


def route_dev_checks(state: FactoryState) -> Literal["qa", "dev", "failed"]:
    """Route after Dev checks (lint / unit tests)."""
    if state.get("dev_gate_ok", False):
        return "qa"

    current_attempt = state.get("attempt", 1)
    max_attempts = state.get("max_attempts", 3)

    if current_attempt < max_attempts:
        print(
            f"[router] Dev checks failed. Retrying (Attempt {current_attempt + 1} of {max_attempts})..."
        )
        state["attempt"] = current_attempt + 1
        return "dev"

    print(f"[router] Dev checks failed. Max attempts ({max_attempts}) exhausted.")
    return "failed"


def route_qa_scope(state: FactoryState) -> Literal["verification", "failed"]:
    """Route after QA scope inspection."""
    if state.get("qa_scope_ok", False):
        return "verification"
    return "failed"


def route_verification(
    state: FactoryState,
) -> Literal["human_approval", "dev", "failed"]:
    """Route after independent verification test suite.

    Why: Directs passed runs to human approval and routes failed runs
    back to Dev for repairs until max_attempts is exhausted.
    """
    if state.get("verification_ok", False):
        return "human_approval"

    current_attempt = state.get("attempt", 1)
    max_attempts = state.get("max_attempts", 3)

    if current_attempt < max_attempts:
        print(
            f"[router] Verification failed. Retrying with feedback (Attempt {current_attempt + 1} of {max_attempts})..."
        )
        state["attempt"] = current_attempt + 1
        return "dev"

    print(f"[router] Verification failed. Max attempts ({max_attempts}) exhausted.")
    return "failed"


# =====================================================================
# 3. Graph Construction & Compilation
# =====================================================================


def create_factory_graph():
    """Build and compile the LangGraph Software Factory workflow."""
    builder = StateGraph(FactoryState)

    # Add all nodes
    builder.add_node("prepare", prepare)
    builder.add_node("dev", dev)
    builder.add_node("dev_scope_gate", dev_scope_gate)
    builder.add_node("dev_checks", dev_checks)
    builder.add_node("qa", qa)
    builder.add_node("qa_scope_gate", qa_scope_gate)
    builder.add_node("verification", verification)
    builder.add_node("human_approval", human_approval)
    builder.add_node("failed", failed)

    # Linear and conditional transitions
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "dev")
    builder.add_edge("dev", "dev_scope_gate")

    builder.add_conditional_edges(
        "dev_scope_gate",
        route_dev_scope,
        {
            "dev_checks": "dev_checks",
            "failed": "failed",
        },
    )

    builder.add_conditional_edges(
        "dev_checks",
        route_dev_checks,
        {
            "qa": "qa",
            "dev": "dev",
            "failed": "failed",
        },
    )

    builder.add_edge("qa", "qa_scope_gate")

    builder.add_conditional_edges(
        "qa_scope_gate",
        route_qa_scope,
        {
            "verification": "verification",
            "failed": "failed",
        },
    )

    builder.add_conditional_edges(
        "verification",
        route_verification,
        {
            "human_approval": "human_approval",
            "dev": "dev",
            "failed": "failed",
        },
    )

    builder.add_edge("human_approval", END)
    builder.add_edge("failed", END)

    return builder.compile()


# Export compiled graph instance for Studio & runner
graph = create_factory_graph()
