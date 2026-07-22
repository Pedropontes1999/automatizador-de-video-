"""Worker QThread da aba Transcrição.

Mesmo padrão do `WatermarkWorker`: a transcrição (download + FFmpeg + Whisper)
é uma sequência de chamadas bloqueantes sem checkpoints, então este worker
não suporta pausar; apenas concluir, falhar ou ser aguardado.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.config.settings import Settings
from src.core.exceptions import AutoShortsError
from src.core.transcribe_pipeline import TranscribeCallbacks, TranscribePipeline
from src.utils.logger import get_logger

logger = get_logger("transcribe_worker")


class TranscribeWorker(QThread):
    """Roda o `TranscribePipeline` em background."""

    progressChanged = Signal(str)           # mensagem de status
    succeeded = Signal(object, str)         # (Transcription, título do vídeo)
    failed = Signal(str)                    # mensagem de erro amigável

    def __init__(self, settings: Settings, source: str) -> None:
        super().__init__()
        self._settings = settings
        self._source = source

    def run(self) -> None:  # noqa: D102 - QThread entry point
        callbacks = TranscribeCallbacks(on_progress=self.progressChanged.emit)
        pipeline = TranscribePipeline(self._settings, callbacks)
        try:
            transcription, title = pipeline.run(self._source)
            self.succeeded.emit(transcription, title)
        except AutoShortsError as exc:
            logger.error("Erro na transcrição: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado na transcrição.")
            self.failed.emit(f"Erro inesperado: {exc}")
