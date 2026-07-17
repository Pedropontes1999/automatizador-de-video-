"""Worker QThread que executa o pipeline sem travar a interface.

A GUI conecta-se aos sinais Qt (thread-safe) e controla a execução via
`TaskControl` (pausar / retomar / cancelar).
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.core.exceptions import AutoShortsError, TaskCancelledError
from src.core.pipeline import PipelineCallbacks
from src.core.task_manager import TaskControl
from src.models.domain import CutCandidate, Project
from src.services.project_service import ProjectService
from src.utils.logger import get_logger

logger = get_logger("worker")


class PipelineWorker(QThread):
    """Roda o `ProjectService.process` em background."""

    # Sinais para a GUI (emitidos da worker thread; Qt entrega na main thread).
    progressChanged = Signal(int, str)      # (percentual, mensagem)
    cutFinished = Signal(object)            # CutCandidate
    projectFinished = Signal(object)        # Project
    failed = Signal(str)                    # mensagem de erro amigável
    cancelled = Signal()

    def __init__(self, service: ProjectService, source: str) -> None:
        super().__init__()
        self._service = service
        self._source = source
        self.control = TaskControl()

    # -- controles chamados pela GUI ------------------------------------ #
    def pause(self) -> None:
        """Pausa no próximo checkpoint do pipeline."""
        self.control.pause()

    def resume_task(self) -> None:
        """Retoma a execução pausada."""
        self.control.resume()

    def cancel(self) -> None:
        """Cancela a execução (aborta no próximo checkpoint)."""
        self.control.cancel()

    # -- execução -------------------------------------------------------- #
    def run(self) -> None:  # noqa: D102 - QThread entry point
        callbacks = PipelineCallbacks(
            on_progress=lambda pct, msg: self.progressChanged.emit(pct, msg),
            on_cut_done=lambda cut: self.cutFinished.emit(cut),
        )
        try:
            project: Project = self._service.process(
                self._source, self.control, callbacks,
            )
            self.projectFinished.emit(project)
        except TaskCancelledError:
            logger.info("Processamento cancelado pelo usuário.")
            self.cancelled.emit()
        except AutoShortsError as exc:
            logger.error("Erro no pipeline: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado no pipeline.")
            self.failed.emit(f"Erro inesperado: {exc}")
