"""LangGraph Software Factory — Terminal CLI (Option 2: Typer).

Why: Provides a developer-friendly terminal interface to run stories,
handle interactive human approvals, inspect state, and launch LangGraph Studio.
"""

from pathlib import Path
import sqlite3
import subprocess
from typing import Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

from factory.graph import create_factory_graph
from factory.runner import ExecutionReporter, RunResult, RunStatus, run_factory

app = typer.Typer(
    name="factory",
    help="LangGraph Software Factory — Multi-agent Orchestration CLI",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


# =====================================================================
# 1. Custom CLI Execution Reporter
# =====================================================================


class CliReporter:
    """Strategy that renders formatted lifecycle events in the terminal."""

    def on_start(self, thread_id: str, action: str) -> None:
        console.print(
            f"[bold blue]▶ [runner][/bold blue] {action} (thread: [cyan]'{thread_id}'[/cyan])"
        )

    def on_node(self, node_name: str) -> None:
        if node_name == "prepare":
            icon = "📋"
        elif "dev" in node_name:
            icon = "💻"
        elif "qa" in node_name:
            icon = "🔍"
        elif "verification" in node_name:
            icon = "🧪"
        elif "human_approval" in node_name:
            icon = "👤"
        else:
            icon = "⚙️ "

        console.print(f"  {icon} [dim]executed:[/dim] [bold]{node_name}[/bold]")

    def on_pause(self, next_nodes: tuple[str, ...]) -> None:
        console.print(
            f"\n[bold yellow]⏸ [runner] Workflow paused at:[/bold yellow] [bold]{next_nodes}[/bold]\n"
        )

    def on_complete(self, status: RunStatus, duration: float) -> None:
        color = "green" if status == "passed" else "red"
        console.print(
            f"\n[bold {color}]✔ [runner] Workflow complete.[/bold {color}] Status: [bold {color}]{status.upper()}[/bold {color}] ({duration:.2f}s)\n"
        )

    def on_error(self, error: Exception) -> None:
        console.print(f"\n[bold red]✖ [runner] Error encountered:[/bold red] {error}\n")


def _print_summary(result: RunResult) -> None:
    """Render a structured summary table for the execution result."""
    table = Table(title="Workflow Execution Summary", show_header=True, header_style="bold magenta")
    table.add_column("Field", style="dim", width=18)
    table.add_column("Value")

    status_color = "green" if result.status == "passed" else ("yellow" if result.interrupted else "red")
    table.add_row("Status", f"[{status_color}]{result.status.upper()}[/{status_color}]")
    table.add_row("Thread ID", result.thread_id)
    table.add_row("Duration", f"{result.metrics.duration_seconds:.2f}s")
    table.add_row("Nodes Executed", f"{result.metrics.total_nodes} ({' -> '.join(result.metrics.nodes_executed)})")
    if result.next_nodes:
        table.add_row("Paused At", f"[yellow]{result.next_nodes}[/yellow]")
    if result.error:
        table.add_row("Error", f"[red]{result.error}[/red]")

    console.print(table)


# =====================================================================
# 2. CLI Commands
# =====================================================================


@app.command()
def run(
    story_id: str = typer.Argument(
        "todo-app",
        help="Story identifier (e.g. 'todo-app', 'crm-004')",
    ),
    thread_id: str | None = typer.Option(
        None,
        "--thread-id",
        "-t",
        help="Deterministic thread ID for persistence",
    ),
    story_path: str | None = typer.Option(
        None,
        "--story-path",
        "-p",
        help="Custom path to story markdown file",
    ),
    checkpoint_db: str = typer.Option(
        ".factory/checkpoints.sqlite",
        "--db",
        help="Path to SQLite persistence database",
    ),
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        help="Prompt interactively when hitting human approval interrupt",
    ),
) -> None:
    """Execute a story through the full factory workflow."""
    console.print(
        Panel.fit(
            f"[bold cyan]LangGraph Software Factory[/bold cyan]\nProcessing Story: [bold green]{story_id}[/bold green]",
            border_style="cyan",
        )
    )

    reporter = CliReporter()
    result = run_factory(
        story_id=story_id,
        story_path=story_path,
        thread_id=thread_id,
        checkpoint_db=checkpoint_db,
        stream=True,
        reporter=reporter,
    )

    # Handle Human Approval Interrupt
    if result.interrupted and "human_approval" in result.next_nodes:
        _print_summary(result)

        if not interactive:
            console.print(
                f"[yellow]Execution paused. Resume anytime via:[/yellow]\n"
                f"[bold]python -m factory.cli resume {result.thread_id} --decision approve[/bold]"
            )
            return

        # Interactive Decision Prompt
        console.print(
            Panel(
                "[bold]Human Approval Gate Reached[/bold]\n"
                "Verification tests passed. How would you like to proceed?\n\n"
                "  • [green]approve[/green] : Mark story complete and finish\n"
                "  • [yellow]retry[/yellow]   : Return to Dev for another iteration\n"
                "  • [red]stop[/red]    : Terminate workflow without completion",
                title="[yellow]Awaiting Human Decision[/yellow]",
                border_style="yellow",
            )
        )

        decision = typer.prompt(
            "Enter decision",
            type=click_choice(["approve", "retry", "stop"]),
            default="approve",
        ).strip().lower()

        console.print(f"\n[cyan]Resuming workflow with decision:[/cyan] [bold]{decision}[/bold]...\n")

        result = run_factory(
            story_id=story_id,
            story_path=story_path,
            thread_id=result.thread_id,
            checkpoint_db=checkpoint_db,
            resume_decision=decision,  # type: ignore[arg-type]
            stream=True,
            reporter=reporter,
        )

    _print_summary(result)


@app.command()
def resume(
    thread_id: str = typer.Argument(
        ...,
        help="Thread ID of the paused workflow run to resume",
    ),
    decision: str | None = typer.Option(
        None,
        "--decision",
        "-d",
        help="Decision choice: 'approve', 'retry', or 'stop'",
    ),
    story_id: str = typer.Option(
        "todo-app",
        "--story-id",
        "-s",
        help="Story identifier associated with the thread",
    ),
    checkpoint_db: str = typer.Option(
        ".factory/checkpoints.sqlite",
        "--db",
        help="Path to SQLite persistence database",
    ),
) -> None:
    """Resume a paused workflow run by thread ID."""
    if not decision:
        decision = typer.prompt(
            "Enter decision",
            type=click_choice(["approve", "retry", "stop"]),
            default="approve",
        ).strip().lower()

    valid_choices = ("approve", "retry", "stop")
    if decision not in valid_choices:
        console.print(f"[bold red]Invalid decision '{decision}'. Must be one of {valid_choices}[/bold red]")
        raise typer.Exit(code=1)

    console.print(
        f"[bold blue]▶ Resuming thread[/bold blue] [cyan]'{thread_id}'[/cyan] with decision: [bold]{decision}[/bold]"
    )

    reporter = CliReporter()
    result = run_factory(
        story_id=story_id,
        thread_id=thread_id,
        checkpoint_db=checkpoint_db,
        resume_decision=decision,  # type: ignore[arg-type]
        stream=True,
        reporter=reporter,
    )

    _print_summary(result)


@app.command()
def status(
    thread_id: str = typer.Argument(
        ...,
        help="Thread ID to inspect in the checkpoint database",
    ),
    checkpoint_db: str = typer.Option(
        ".factory/checkpoints.sqlite",
        "--db",
        help="Path to SQLite persistence database",
    ),
) -> None:
    """Inspect state and checkpoint metadata for a specific thread."""
    db_file = Path(checkpoint_db)
    if not db_file.exists():
        console.print(f"[bold red]Database file '{checkpoint_db}' not found.[/bold red]")
        raise typer.Exit(code=1)

    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    try:
        checkpointer = SqliteSaver(conn)
        graph = create_factory_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = graph.get_state(config)

        if not snapshot.values:
            console.print(f"[yellow]No checkpoints found for thread '{thread_id}'.[/yellow]")
            return

        table = Table(title=f"Thread Checkpoint: {thread_id}", show_header=True)
        table.add_column("Key", style="dim")
        table.add_column("Value")

        table.add_row("Status", str(snapshot.values.get("status", "unknown")))
        table.add_row("Story ID", str(snapshot.values.get("story_id", "unknown")))
        table.add_row("Attempt", str(snapshot.values.get("attempt", 1)))
        table.add_row("Next Node(s)", str(snapshot.next or "(none)"))
        table.add_row("Dev Scope OK", str(snapshot.values.get("dev_scope_ok", "-")))
        table.add_row("Dev Gate OK", str(snapshot.values.get("dev_gate_ok", "-")))
        table.add_row("QA Scope OK", str(snapshot.values.get("qa_scope_ok", "-")))
        table.add_row("Verification OK", str(snapshot.values.get("verification_gate_ok", "-")))

        console.print(table)
    finally:
        conn.close()


@app.command()
def studio(
    port: int = typer.Option(
        2024,
        "--port",
        "-p",
        help="Local port for LangGraph dev server",
    ),
) -> None:
    """Launch the native LangGraph Studio visual inspection UI."""
    console.print(
        Panel.fit(
            f"[bold magenta]🎨 Launching LangGraph Studio[/bold magenta]\n"
            f"Port: [bold]{port}[/bold]\n"
            f"Config: [dim]langgraph.json[/dim]",
            border_style="magenta",
        )
    )
    cmd = ["uv", "run", "langgraph", "dev", "--port", str(port)]
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        console.print("\n[yellow]LangGraph Studio stopped.[/yellow]")


def click_choice(choices: list[str]):
    """Helper returning a click Choice type for input validation."""
    import click

    return click.Choice(choices, case_sensitive=False)


if __name__ == "__main__":
    app()
