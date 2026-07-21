"""Worker QThread da aba Download: baixa um vídeo do YouTube via yt-dlp.

Chamada bloqueante única (sem checkpoints), então não suporta pausar;
apenas concluir, falhar ou ser aguardado/terminado ao fechar o app.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.core.exceptions import AutoShortsError
from src.utils.logger import get_logger
from src.video.downloader import download_video

logger = get_logger("download_worker")


class DownloadWorker(QThread):
    """Baixa um vídeo do YouTube em background."""

    progressChanged = Signal(int, str)  # percentual (0-100), mensagem
    succeeded = Signal(str)             # caminho do vídeo baixado
    failed = Signal(str)                # mensagem de erro amigável

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            path = download_video(
                self._url,
                progress=lambda pct, msg: self.progressChanged.emit(int(pct), msg),
            )
            self.succeeded.emit(str(path))
        except AutoShortsError as exc:
            logger.error("Erro ao baixar vídeo: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado ao baixar vídeo.")
            self.failed.emit(f"Erro inesperado: {exc}")
