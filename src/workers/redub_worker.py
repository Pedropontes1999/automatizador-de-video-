"""Worker QThread da Redublagem: transcrição + separação de voz/música +
narração de IA sincronizada, substituindo a voz do narrador original.

Mesmo padrão do `PipelineWorker`/`VideoEditorWorker`: roda em background,
controla pausa/cancelamento via `TaskControl` e entrega o progresso por
sinais Qt.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.config.settings import Settings
from src.core.exceptions import AutoShortsError, TaskCancelledError
from src.core.redub_pipeline import RedubCallbacks, RedubPipeline
from src.core.task_manager import TaskControl
from src.utils.logger import get_logger

logger = get_logger("redub_worker")


class RedubWorker(QThread):
    """Roda o `RedubPipeline` em background."""

    progressChanged = Signal(int, str)      # (percentual, mensagem)
    finished_ok = Signal(str)               # caminho do MP4 final
    failed = Signal(str)                    # mensagem de erro amigável
    cancelled = Signal()

    def __init__(self, settings: Settings, source: str) -> None:
        super().__init__()
        self._settings = settings
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
        callbacks = RedubCallbacks(
            on_progress=lambda pct, msg: self.progressChanged.emit(pct, msg),
        )
        pipeline = RedubPipeline(self._settings, callbacks)
        try:
            output_path = pipeline.run(self._source, self.control)
            self.finished_ok.emit(str(output_path))
        except TaskCancelledError:
            logger.info("Redublagem cancelada pelo usuário.")
            self.cancelled.emit()
        except AutoShortsError as exc:
            logger.error("Erro na redublagem: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado na redublagem.")
            self.failed.emit(f"Erro inesperado: {exc}")
