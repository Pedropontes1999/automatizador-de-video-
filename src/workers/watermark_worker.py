"""Worker QThread da aba Remover Marca d'Água.

A exportação via FFmpeg é uma chamada bloqueante única (sem checkpoints),
então este worker não suporta pausar; apenas concluir, falhar ou ser aguardado.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from src.core.exceptions import AutoShortsError
from src.utils.logger import get_logger
from src.video.watermark_remover import (
    WatermarkRegion,
    blur_watermark,
    cover_watermark,
    remove_and_cover_watermark,
    remove_watermark,
)

logger = get_logger("watermark_worker")


class WatermarkWorker(QThread):
    """Remove ou cobre a marca d'água de um vídeo em background."""

    progressChanged = Signal(str)   # mensagem de status
    succeeded = Signal(str)         # caminho do MP4 exportado
    failed = Signal(str)            # mensagem de erro amigável

    def __init__(
        self,
        source: str,
        output_path: str | Path,
        region: WatermarkRegion,
        method: str = "remove",  # "remove" (delogo) | "cover" (colar) | "remove_cover" (os dois) | "blur"
        cover_image: str | Path | None = None,
        use_gpu: bool = True,
        crf: int = 20,
        frame_size: tuple[int, int] | None = None,
    ) -> None:
        super().__init__()
        self._source = source
        self._output_path = Path(output_path)
        self._region = region
        self._method = method
        self._cover_image = cover_image
        self._use_gpu = use_gpu
        self._crf = crf
        self._frame_size = frame_size

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            if self._method == "blur":
                blur_watermark(
                    self._source, self._output_path, self._region,
                    use_gpu=self._use_gpu, crf=self._crf, frame_size=self._frame_size,
                    on_progress=self.progressChanged.emit,
                )
            elif self._method == "remove_cover":
                remove_and_cover_watermark(
                    self._source, self._output_path, self._region, self._cover_image,
                    use_gpu=self._use_gpu, crf=self._crf, frame_size=self._frame_size,
                    on_progress=self.progressChanged.emit,
                )
            elif self._method == "cover":
                cover_watermark(
                    self._source, self._output_path, self._region, self._cover_image,
                    use_gpu=self._use_gpu, crf=self._crf, frame_size=self._frame_size,
                    on_progress=self.progressChanged.emit,
                )
            else:
                remove_watermark(
                    self._source, self._output_path, self._region,
                    use_gpu=self._use_gpu, crf=self._crf, frame_size=self._frame_size,
                    on_progress=self.progressChanged.emit,
                )
            self.succeeded.emit(str(self._output_path))
        except AutoShortsError as exc:
            logger.error("Erro ao tratar marca d'água: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado ao tratar marca d'água.")
            self.failed.emit(f"Erro inesperado: {exc}")
