"""Worker QThread que baixa só o áudio de um link do YouTube sem travar a GUI."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.core.exceptions import DownloadError
from src.utils.logger import get_logger
from src.video.downloader import download_audio

logger = get_logger("audio_download_worker")


class AudioDownloadWorker(QThread):
    """Baixa o áudio (MP3) de um link do YouTube em background."""

    progressChanged = Signal(float, str)   # (percentual 0-100, mensagem)
    downloaded = Signal(str)               # caminho do MP3 baixado
    failed = Signal(str)                   # mensagem de erro amigável

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            path = download_audio(
                self._url,
                progress=lambda pct, msg: self.progressChanged.emit(pct, msg),
            )
            self.downloaded.emit(str(path))
        except DownloadError as exc:
            logger.error("Falha ao baixar áudio: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado ao baixar áudio.")
            self.failed.emit(f"Erro inesperado: {exc}")
