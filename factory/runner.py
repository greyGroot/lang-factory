"""Programmatic Runner Interface for the LangGraph Software Factory.

Why: Decouples factory workflow execution from specific CLI or test scripts, exposing
a clean SDK-style entrypoint `run_factory` callable by external agents (Antigravity, Codex)
or the standalone CLI (Step 14).
"""

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import time
from typing import Any, Literal, Protocol
import uuid

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from factory.graph import create_factory_graph

# =====================================================================
# 1. Types & Data Contracts
# =====================================================================

RunStatus = Literal["pending", "running", "passed", "failed", "stopped", "interrupted"]


@dataclass
class RunMetrics:
    """Execution statistics and performance metrics."""

    duration_seconds: float = 0.0
    nodes_executed: list[str] = field(default_factory=list)

    @property
    def total_nodes(self) -> int:
        return len(self.nodes_executed)


@dataclass
class RunResult:
    """Structured execution result returned by run_factory.

    Why: Standardizes the return contract across completed runs, interrupted runs,
    and failures for consumption by external agents, CI pipelines, or CLI.
    """

    status: RunStatus
    thread_id: str
    interrupted: bool
    next_nodes: tuple[str, ...]
    state: dict[str, Any]
    metrics: RunMetrics
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result into a serializable dictionary for external callers."""
        return {
            "status": self.status,
            "thread_id": self.thread_id,
            "interrupted": self.interrupted,
            "next_nodes": list(self.next_nodes),
            "state": self.state,
            "metrics": {
                "duration_seconds": round(self.metrics.duration_seconds, 3),
                "nodes_executed": self.metrics.nodes_executed,
                "total_nodes": self.metrics.total_nodes,
            },
            "error": self.error,
        }


# =====================================================================
# 2. Strategy Pattern: Execution Reporters
# =====================================================================


class ExecutionReporter(Protocol):
    """Protocol defining the reporting strategy for runner lifecycle events."""

    def on_start(self, thread_id: str, action: str) -> None: ...
    def on_node(self, node_name: str) -> None: ...
    def on_pause(self, next_nodes: tuple[str, ...]) -> None: ...
    def on_complete(self, status: RunStatus, duration: float) -> None: ...
    def on_error(self, error: Exception) -> None: ...


class ConsoleReporter:
    """Strategy that prints formatted workflow progress events to the console."""

    def on_start(self, thread_id: str, action: str) -> None:
        print(f"[runner] {action} for thread: '{thread_id}'...")

    def on_node(self, node_name: str) -> None:
        print(f"  [runner:node] Executed: {node_name}")

    def on_pause(self, next_nodes: tuple[str, ...]) -> None:
        print(
            f"[runner] Execution paused at node(s): {next_nodes}. Awaiting human decision."
        )

    def on_complete(self, status: RunStatus, duration: float) -> None:
        print(
            f"[runner] Execution finished with status: '{status}' ({duration:.2f}s)."
        )

    def on_error(self, error: Exception) -> None:
        print(f"[runner] Execution halted due to error: {error}")


class SilentReporter:
    """Null Object strategy that suppresses all output."""

    def on_start(self, thread_id: str, action: str) -> None:
        pass

    def on_node(self, node_name: str) -> None:
        pass

    def on_pause(self, next_nodes: tuple[str, ...]) -> None:
        pass

    def on_complete(self, status: RunStatus, duration: float) -> None:
        pass

    def on_error(self, error: Exception) -> None:
        pass


# =====================================================================
# 3. Main Runner Function
# =====================================================================


def run_factory(
    story_id: str = "todo-app",
    story_path: str | None = None,
    thread_id: str | None = None,
    checkpoint_db: str = ".factory/checkpoints.sqlite",
    resume_decision: Literal["approve", "retry", "stop"] | None = None,
    stream: bool = True,
    reporter: ExecutionReporter | None = None,
) -> RunResult:
    """Execute or resume the software factory workflow programmatically.

    Args:
        story_id: Identifier of the story to process (e.g. 'todo-app').
        story_path: Path to story markdown file. Defaults to 'docs/stories/{story_id}/story.md'.
        thread_id: Deterministic thread ID for checkpoint persistence. Auto-generates UUID if None.
        checkpoint_db: Path to the SQLite persistence database.
        resume_decision: Human decision ('approve', 'retry', 'stop') when resuming an interrupt.
        stream: If True (default), prints node transitions via ConsoleReporter. If False, runs quietly.
        reporter: Custom ExecutionReporter strategy. If None, uses ConsoleReporter (if stream) or SilentReporter.

    Returns:
        RunResult dataclass with final status, thread ID, interrupt flag, next nodes, state, and metrics.
    """
    start_time = time.perf_counter()
    nodes_executed: list[str] = []

    # 1. Обираємо стратегію звітування один раз (без розсипу if stream)
    if reporter is None:
        reporter = ConsoleReporter() if stream else SilentReporter()

    # 2. Гарантуємо наявність директорії для SQLite
    db_file = Path(checkpoint_db)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # 3. Генеруємо унікальний thread_id через UUID, якщо не передано викликачем
    active_thread_id = thread_id or f"{story_id}-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": active_thread_id}}

    # 4. Підключаємося до SQLite
    conn = sqlite3.connect(str(db_file), check_same_thread=False)

    try:
        checkpointer = SqliteSaver(conn)
        graph = create_factory_graph(checkpointer=checkpointer)

        # 5. Визначаємо вхідні дані для запуску або відновлення
        if resume_decision is not None:
            input_payload = Command(resume=resume_decision)
            action = f"Resuming with decision '{resume_decision}'"
        else:
            current_snapshot = graph.get_state(config)
            if current_snapshot.values:
                input_payload = None
                action = "Continuing existing workflow"
            else:
                input_payload = {
                    "story_id": story_id,
                    "story_path": story_path or f"docs/stories/{story_id}/story.md",
                    "repo_root": ".",
                }
                action = "Starting fresh workflow"

        reporter.on_start(active_thread_id, action)

        # 6. Виконуємо потік графів
        for event in graph.stream(input_payload, config=config):
            for node_name in event.keys():
                nodes_executed.append(node_name)
                reporter.on_node(node_name)

        # 7. Зчитуємо фінальний стан
        snapshot = graph.get_state(config)
        state_values = dict(snapshot.values) if snapshot.values else {}
        next_nodes = tuple(snapshot.next) if snapshot.next else ()
        is_interrupted = len(next_nodes) > 0

        final_status: RunStatus = (
            "interrupted"
            if is_interrupted
            else state_values.get("status", "failed")
        )

        duration = time.perf_counter() - start_time
        metrics = RunMetrics(duration_seconds=duration, nodes_executed=nodes_executed)

        if is_interrupted:
            reporter.on_pause(next_nodes)
        else:
            reporter.on_complete(final_status, duration)

        return RunResult(
            status=final_status,
            thread_id=active_thread_id,
            interrupted=is_interrupted,
            next_nodes=next_nodes,
            state=state_values,
            metrics=metrics,
            error=None,
        )

    except Exception as exc:
        # Перехоплюємо неочікувані помилки виконання для безпечного повернення клієнту
        duration = time.perf_counter() - start_time
        reporter.on_error(exc)
        metrics = RunMetrics(duration_seconds=duration, nodes_executed=nodes_executed)

        return RunResult(
            status="failed",
            thread_id=active_thread_id,
            interrupted=False,
            next_nodes=(),
            state={},
            metrics=metrics,
            error=str(exc),
        )

    finally:
        # Закриваємо з'єднання з SQLite для запобігання lock-файлів на Windows
        conn.close()
