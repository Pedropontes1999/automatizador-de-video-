"""Worker QThread da aba Cortar Vídeo: remove os trechos marcados manualmente.

A exportação via FFmpeg é uma chamada bloqueante única (sem checkpoints),
então este worker não suporta pausar; apenas concluir, falhar ou ser aguardado.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from src.core.exceptions import AutoShortsError
from src.utils.logger import get_logger
from src.video.trim_editor import CutRange, remove_ranges

logger = get_logger("trim_worker")


class TrimWorker(QThread):
    """Remove os trechos marcados de um vídeo em background."""

    progressChanged = Signal(str)   # mensagem de status
    succeeded = Signal(str)         # caminho do MP4 exportado
    failed = Signal(str)            # mensagem de erro amigável

    def __init__(
        self,
        source: str,
        output_path: str | Path,
        ranges: list[CutRange],
        use_gpu: bool = True,
    ) -> None:
        super().__init__()
        self._source = source
        self._output_path = Path(output_path)
        self._ranges = ranges
        self._use_gpu = use_gpu

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            remove_ranges(
                self._source, self._output_path, self._ranges,
                use_gpu=self._use_gpu, on_progress=self.progressChanged.emit,
            )
            self.succeeded.emit(str(self._output_path))
        except AutoShortsError as exc:
            logger.error("Erro ao cortar vídeo: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado ao cortar vídeo.")
            self.failed.emit(f"Erro inesperado: {exc}")
