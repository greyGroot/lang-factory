from dataclasses import dataclass
from typing import Literal, Protocol

@dataclass
class WorkerResult:
    status: Literal["success", "error", "timeout"]
    response: str
    conversation_id: str | None = None
    raw_output_path: str | None = None

class CodingWorker(Protocol):
    """Interface for factory workers. All workers must implement `run`."""
    def run(self, prompt: str, cwd: str, conversation_id: str | None = None) -> WorkerResult:
        ...

