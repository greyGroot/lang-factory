from typing import Any, Literal, Optional, TypedDict

LifecycleStatus = Literal[
    "pending",
    "running",
    "waiting_human",
    "passed",
    "failed",
    "stopped",
]

class FactoryState(TypedDict, total=False):
    story_id: str
    story_path: str
    repo_root: str

    attempt: int
    max_attempts: int

    dev_conversation_id: Optional[str]
    qa_conversation_id: Optional[str]

    dev_status: Optional[str]
    dev_scope_ok: Optional[bool]
    dev_gate_ok: Optional[bool]

    qa_status: Optional[str]
    qa_scope_ok: Optional[bool]
    verification_ok: Optional[bool]

    failure_report: Optional[dict[str, Any]]
    changed_files: list[str]

    status: LifecycleStatus