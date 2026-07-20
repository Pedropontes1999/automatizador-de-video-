"""Download de vídeos do YouTube via yt-dlp.

IMPORTANTE: use apenas com vídeos próprios ou cujo uso seja autorizado.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, TypeVar

from src.config.constants import DOWNLOADS_DIR
from src.core.exceptions import DownloadError
from src.utils.logger import get_logger

logger = get_logger("downloader")

ProgressFn = Callable[[float, str], None]  # (percentual 0-100, mensagem)

# O YouTube às vezes responde 403/erros de rede passageiros (throttling,
# instabilidade momentânea) que somem numa nova tentativa — sem isso, um
# blip de alguns segundos derrubava o download inteiro.
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 4

_T = TypeVar("_T")


def _with_retries(description: str, action: Callable[[], _T]) -> _T:
    """Roda `action`, tentando de novo em caso de falha (rede/YouTube)."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - yt-dlp lança tipos variados
            last_exc = exc
            if attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "%s falhou (tentativa %d/%d): %s — tentando de novo em %ds...",
                    description, attempt, _MAX_ATTEMPTS, exc, _RETRY_DELAY_SECONDS,
                )
                time.sleep(_RETRY_DELAY_SECONDS)
    assert last_exc is not None
    raise last_exc


def is_youtube_url(text: str) -> bool:
    """Verifica se o texto é um link do YouTube."""
    text = text.strip().lower()
    return text.startswith(("http://", "https://")) and (
        "youtube.com" in text or "youtu.be" in text
    )


def download_video(url: str, progress: ProgressFn | None = None) -> Path:
    """Baixa o vídeo em MP4 (melhor qualidade até 1080p) para downloads/.

    Args:
        url: link do YouTube autorizado pelo usuário.
        progress: callback (percentual, mensagem) para a GUI.

    Returns:
        Caminho do arquivo baixado.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise DownloadError("yt-dlp não instalado. Rode: pip install yt-dlp") from exc

    def _hook(d: dict) -> None:
        if progress is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = (done / total * 100) if total else 0.0
            progress(pct, f"Baixando... {pct:.0f}%")
        elif d.get("status") == "finished":
            progress(100.0, "Download concluído. Processando...")

    options = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(DOWNLOADS_DIR / "%(title).80s [%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_hook],
    }
    # Informa ao yt-dlp onde está o FFmpeg (necessário para juntar vídeo+áudio
    # quando o PATH do sistema ainda não foi atualizado).
    from src.utils.ffmpeg_utils import get_ffmpeg_dir

    ffmpeg_dir = get_ffmpeg_dir()
    if ffmpeg_dir is not None:
        options["ffmpeg_location"] = str(ffmpeg_dir)
    def _download() -> Path:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
        if not path.exists():  # fallback: alguns formatos mantêm a extensão original
            path = Path(ydl.prepare_filename(info))
        return path

    try:
        path = _with_retries("Download do vídeo", _download)
        logger.info("Vídeo baixado: %s", path)
        return path
    except Exception as exc:  # noqa: BLE001 - yt-dlp lança tipos variados
        raise DownloadError(f"Falha ao baixar o vídeo: {exc}") from exc


def download_audio(url: str, progress: ProgressFn | None = None) -> Path:
    """Baixa somente o áudio de um vídeo do YouTube, como MP3, para downloads/.

    Usado para música de fundo: evita baixar o vídeo inteiro quando só a
    trilha sonora interessa.

    Args:
        url: link do YouTube autorizado pelo usuário.
        progress: callback (percentual, mensagem) para a GUI.

    Returns:
        Caminho do MP3 baixado.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise DownloadError("yt-dlp não instalado. Rode: pip install yt-dlp") from exc

    def _hook(d: dict) -> None:
        if progress is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = (done / total * 100) if total else 0.0
            progress(pct, f"Baixando áudio... {pct:.0f}%")
        elif d.get("status") == "finished":
            progress(100.0, "Download concluído. Convertendo para MP3...")

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(DOWNLOADS_DIR / "%(title).80s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_hook],
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    from src.utils.ffmpeg_utils import get_ffmpeg_dir

    ffmpeg_dir = get_ffmpeg_dir()
    if ffmpeg_dir is not None:
        options["ffmpeg_location"] = str(ffmpeg_dir)
    def _download() -> Path:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info)).with_suffix(".mp3")
        if not path.exists():
            raise DownloadError(
                "Áudio baixado, mas o MP3 não foi encontrado após a conversão "
                "(verifique se o FFmpeg está instalado)."
            )
        return path

    try:
        path = _with_retries("Download do áudio", _download)
        logger.info("Áudio baixado: %s", path)
        return path
    except DownloadError:
        raise
    except Exception as exc:  # noqa: BLE001 - yt-dlp lança tipos variados
        raise DownloadError(f"Falha ao baixar o áudio: {exc}") from exc
