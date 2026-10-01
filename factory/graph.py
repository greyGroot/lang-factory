from typing import Literal

from langgraph.graph import END, START, StateGraph

from factory.gates import run_verification_gate
from factory.scope import enforce_scope
from factory.state import FactoryState

# =====================================================================
# 1. Mock Node Functions (Stub handlers returning partial state updates)
# =====================================================================


def prepare(state: FactoryState) -> dict:
    """Initialize run context and default attempt counter."""
    print("[prepare] Initializing factory workflow run...")
    return {
        "status": "running",
        "attempt": state.get("attempt", 1),
        "max_attempts": state.get("max_attempts", 3),
        "changed_files": [],
        "failure_report": None,
    }


def dev(state: FactoryState) -> dict:
    """Mock Dev worker: simulates writing/modifying code."""
    print(f"[dev] Executing Dev agent (Attempt {state.get('attempt', 1)})...")
    return {
        "dev_status": "success",
        "dev_conversation_id": "mock-dev-session-001",
        "changed_files": ["src/todo.py", "tests/test_todo.py"],
    }


def dev_scope_gate(state: FactoryState) -> dict:
    """Mock Dev scope gate: checks if Dev stayed within permitted paths."""
    print("[dev_scope_gate] Checking Dev write scope...")
    return {
        "dev_scope_ok": True,
    }


def dev_checks(state: FactoryState) -> dict:
    """Mock Dev checks: runs deterministic lint & unit tests."""
    print("[dev_checks] Running deterministic lint and unit tests...")
    return {
        "dev_gate_ok": True,
    }


def qa(state: FactoryState) -> dict:
    """Mock QA worker: simulates writing verification tests."""
    print("[qa] Executing QA agent...")
    return {
        "qa_status": "success",
        "qa_conversation_id": "mock-qa-session-001",
        "changed_files": ["verification/todo-app/test_verify.py"],
    }


def qa_scope_gate(state: FactoryState) -> dict:
    """Inspect Git changes to ensure QA only modified verification/{story_id}/**."""
    story_id = state.get("story_id", "todo-app")
    repo_root = state.get("repo_root", ".")
    print(f"[qa_scope_gate] Checking QA write scope for story '{story_id}'...")
    # Enforce QA write boundaries using git status
    scope_result = enforce_scope(role="qa", story_id=story_id, cwd=repo_root)
    return {
        "qa_scope_ok": scope_result.ok,
        "changed_files": scope_result.changed_files,
    }


def verification(state: FactoryState) -> dict:
    """Run independent verification tests located in verification/{story_id}."""
    story_id = state.get("story_id", "todo-app")
    repo_root = state.get("repo_root", ".")
    print(f"[verification] Executing verification suite for '{story_id}'...")
    # Run the dedicated verification gate
    gate_result = run_verification_gate(story_id=story_id, cwd=repo_root)

    if gate_result.ok:
        print(f"[verification] PASS: Verification tests passed for '{story_id}'.")
    else:
        print(
            f"[verification] FAIL: Verification tests failed (exit code {gate_result.exit_code})."
        )
        if gate_result.stderr:
            print(f"[verification] stderr: {gate_result.stderr[:200]}")

    return {
        "verification_ok": gate_result.ok,
    }


def human_approval(state: FactoryState) -> dict:
    """Mock Human approval: simulates approval to pass."""
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
    # Retry loop if retries remain
    if state.get("attempt", 1) < state.get("max_attempts", 3):
        return "dev"
    return "failed"


def route_qa_scope(state: FactoryState) -> Literal["verification", "failed"]:
    """Route after QA scope inspection."""
    if state.get("qa_scope_ok", False):
        return "verification"
    return "failed"


def route_verification(
    state: FactoryState,
) -> Literal["human_approval", "dev", "failed"]:
    """Route after independent verification test suite."""
    if state.get("verification_ok", False):
        return "human_approval"
    # Retry loop: feedback to Dev if attempts left
    if state.get("attempt", 1) < state.get("max_attempts", 3):
        return "dev"
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
