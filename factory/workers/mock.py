from .base import CodingWorker, WorkerResult

class MockWorker:
    def __init__(
        self,
        status: str = "success",
        response: str = "Mock response",
    ) -> None:
        self.status = status
        self.response = response

    def run(self, prompt: str, cwd: str, conversation_id: str | None = None) -> WorkerResult:
        
        return WorkerResult(
            status=self.status,
            response=self.response,
            conversation_id = conversation_id or "mock-conv-123",
            raw_output_path=None,
        )