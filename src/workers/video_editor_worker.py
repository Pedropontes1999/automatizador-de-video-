"""Worker QThread do Editor de Vídeo: narração + estática + vídeo original.

Mesmo padrão do `PipelineWorker` (Shorts): roda em background, controla
pausa/cancelamento via `TaskControl` e entrega o progresso por sinais Qt.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.config.settings import Settings
from src.core.exceptions import AutoShortsError, TaskCancelledError
from src.core.task_manager import TaskControl
from src.core.video_editor_pipeline import VideoEditCallbacks, VideoEditPipeline
from src.utils.logger import get_logger

logger = get_logger("editor_worker")


class VideoEditorWorker(QThread):
    """Roda o `VideoEditPipeline` em background."""

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
        callbacks = VideoEditCallbacks(
            on_progress=lambda pct, msg: self.progressChanged.emit(pct, msg),
        )
        pipeline = VideoEditPipeline(self._settings, callbacks)
        try:
            output_path = pipeline.run(self._source, self.control)
            self.finished_ok.emit(str(output_path))
        except TaskCancelledError:
            logger.info("Edição cancelada pelo usuário.")
            self.cancelled.emit()
        except AutoShortsError as exc:
            logger.error("Erro no editor de vídeo: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado no editor de vídeo.")
            self.failed.emit(f"Erro inesperado: {exc}")
