"""Workers QThread da Redublagem, um por etapa do `RedubPipeline`:

- `RedubPrepareWorker` — transcrição + separação de voz/música (etapa 1).
- `RedubGenerateWorker` — narração de IA sincronizada + montagem do vídeo
  final, a partir do texto (revisado pelo usuário) devolvido pela etapa 1.

Mesmo padrão do `PipelineWorker`/`VideoEditorWorker`: rodam em background,
controlam pausa/cancelamento via `TaskControl` e entregam o progresso por
sinais Qt.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.config.settings import Settings
from src.core.exceptions import AutoShortsError, TaskCancelledError
from src.core.redub_pipeline import RedubCallbacks, RedubPipeline, RedubPreparation
from src.core.task_manager import TaskControl
from src.utils.logger import get_logger

logger = get_logger("redub_worker")


class RedubPrepareWorker(QThread):
    """Roda a etapa 1 do `RedubPipeline` (transcrição) em background."""

    progressChanged = Signal(int, str)      # (percentual, mensagem)
    succeeded = Signal(object)              # RedubPreparation
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
            preparation = pipeline.prepare(self._source, self.control)
            self.succeeded.emit(preparation)
        except TaskCancelledError:
            logger.info("Transcrição da redublagem cancelada pelo usuário.")
            self.cancelled.emit()
        except AutoShortsError as exc:
            logger.error("Erro na transcrição da redublagem: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado na transcrição da redublagem.")
            self.failed.emit(f"Erro inesperado: {exc}")


class RedubGenerateWorker(QThread):
    """Roda a etapa 2 do `RedubPipeline` (nova narração + montagem final)."""

    progressChanged = Signal(int, str)      # (percentual, mensagem)
    finished_ok = Signal(str)               # caminho do MP4 final
    failed = Signal(str)                    # mensagem de erro amigável
    cancelled = Signal()

    def __init__(
        self, settings: Settings, preparation: RedubPreparation, texts: list[str],
    ) -> None:
        super().__init__()
        self._settings = settings
        self._preparation = preparation
        self._texts = texts
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
            output_path = pipeline.generate(self._preparation, self._texts, self.control)
            self.finished_ok.emit(str(output_path))
        except TaskCancelledError:
            logger.info("Geração da redublagem cancelada pelo usuário.")
            self.cancelled.emit()
        except AutoShortsError as exc:
            logger.error("Erro na geração da redublagem: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado na geração da redublagem.")
            self.failed.emit(f"Erro inesperado: {exc}")
