import json
import os
import subprocess
from typing import Literal
from factory.workers.base import WorkerResult


class AntigravityWorker:
    """Адаптер для запуску headless CLI Antigravity (agy)."""

    def __init__(self, cli_bin: str | None = None) -> None:
        # Визначаємо шлях до бінарника: з аргументу, змінної оточення або дефолтну команду "agy"
        self.cli_bin = cli_bin or os.getenv("ANTIGRAVITY_BIN", "agy")

    def run(
        self,
        prompt: str,
        cwd: str,
        conversation_id: str | None = None,
    ) -> WorkerResult:
        """Запускає agy CLI у робочій директорії, стрімить вивід і повертає WorkerResult."""

        # Формуємо прапорці автономного виклику: неінтерактивний друк, JSON та пісочниця
        cmd = [
            self.cli_bin,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--sandbox",
        ]

        # Додаємо ідентифікатор сесії для збереження контексту під час циклів виправлень
        if conversation_id:
            cmd.extend(["--conversation", conversation_id])

        try:
            # Запускаємо процес із рядковою буферизацією (bufsize=1) для потокового читання stdout
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            stdout_lines: list[str] = []

            # Читаємо stdout у реальному часі, друкуємо в консоль і накопичуємо рядки
            if process.stdout:
                for line in process.stdout:
                    print(line, end="", flush=True)
                    stdout_lines.append(line)

            # Очікуємо завершення процесу та забираємо вміст stderr
            process.wait()
            _, stderr_content = process.communicate()

            full_stdout = "".join(stdout_lines).strip()

            # Якщо код повернення не 0 — фіксуємо помилку виконання CLI
            if process.returncode != 0:
                error_msg = stderr_content.strip() or full_stdout or "Unknown agy CLI error"
                return WorkerResult(
                    status="error",
                    response=error_msg,
                    conversation_id=conversation_id,
                )

            # Парсимо фінальну JSON-відповідь
            data = json.loads(full_stdout)

            # Нормалізуємо статус до нижнього регістру відповідно до контракту WorkerResult
            raw_status = data.get("status", "error").lower()
            status: Literal["success", "error", "timeout"] = (
                "success" if raw_status == "success" else "error"
            )

            return WorkerResult(
                status=status,
                response=data.get("response", ""),
                conversation_id=data.get("conversation_id", conversation_id),
            )

        except FileNotFoundError:
            # Обробка відсутності виконуваного файлу в PATH без крашу програми
            return WorkerResult(
                status="error",
                response=f"CLI executable '{self.cli_bin}' not found in PATH.",
                conversation_id=conversation_id,
            )
        except json.JSONDecodeError as exc:
            # Обробка невалідного JSON у виводі процесу
            return WorkerResult(
                status="error",
                response=f"Failed to parse JSON output: {exc}. Raw output: {full_stdout}",
                conversation_id=conversation_id,
            )