"""Gerenciador de tarefas com fila, cancelamento, pausa e retomada.

O pipeline consulta o `TaskControl` entre as etapas (e dentro de loops longos)
através de `checkpoint()`: se pausado, bloqueia até retomar; se cancelado,
lança `TaskCancelledError` para abortar de forma limpa.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from src.core.exceptions import TaskCancelledError
from src.utils.logger import get_logger

logger = get_logger("tasks")


class TaskControl:
    """Controle thread-safe de pausa/cancelamento de uma tarefa."""

    def __init__(self) -> None:
        self._cancel_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()  # começa "rodando"

    # -- comandos (chamados pela GUI) ---------------------------------- #
    def cancel(self) -> None:
        """Solicita cancelamento; também acorda tarefas pausadas."""
        self._cancel_event.set()
        self._resume_event.set()

    def pause(self) -> None:
        """Pausa a tarefa no próximo checkpoint."""
        self._resume_event.clear()

    def resume(self) -> None:
        """Retoma uma tarefa pausada."""
        self._resume_event.set()

    # -- consultas (chamadas pelo pipeline) ----------------------------- #
    @property
    def cancelled(self) -> bool:
        """True se o cancelamento foi solicitado."""
        return self._cancel_event.is_set()

    @property
    def paused(self) -> bool:
        """True se a tarefa está pausada."""
        return not self._resume_event.is_set()

    def checkpoint(self) -> None:
        """Ponto de verificação: bloqueia se pausado, aborta se cancelado."""
        self._resume_event.wait()
        if self._cancel_event.is_set():
            raise TaskCancelledError("Tarefa cancelada pelo usuário.")


@dataclass
class QueuedTask:
    """Item da fila de processamento."""

    name: str
    run: Callable[[TaskControl], None]
    control: TaskControl = field(default_factory=TaskControl)


class TaskQueue:
    """Fila FIFO simples de tarefas com execução sequencial em worker thread.

    A GUI usa `enqueue()` e controla a tarefa corrente via `current.control`.
    """

    def __init__(self) -> None:
        self._queue: deque[QueuedTask] = deque()
        self._lock = threading.Lock()
        self.current: QueuedTask | None = None

    def enqueue(self, task: QueuedTask) -> None:
        """Adiciona tarefa ao fim da fila."""
        with self._lock:
            self._queue.append(task)
        logger.info("Tarefa enfileirada: %s (fila: %d)", task.name, len(self._queue))

    def next_task(self) -> QueuedTask | None:
        """Remove e retorna a próxima tarefa (ou None se vazia)."""
        with self._lock:
            self.current = self._queue.popleft() if self._queue else None
        return self.current

    def clear(self) -> None:
        """Esvazia a fila e cancela a tarefa atual."""
        with self._lock:
            self._queue.clear()
        if self.current is not None:
            self.current.control.cancel()

    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)
