"""Download de vídeos do YouTube via yt-dlp.

IMPORTANTE: use apenas com vídeos próprios ou cujo uso seja autorizado.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.config.constants import DOWNLOADS_DIR
from src.core.exceptions import DownloadError
from src.utils.logger import get_logger

logger = get_logger("downloader")

ProgressFn = Callable[[float, str], None]  # (percentual 0-100, mensagem)


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
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
        if not path.exists():  # fallback: alguns formatos mantêm a extensão original
            path = Path(ydl.prepare_filename(info))
        logger.info("Vídeo baixado: %s", path)
        return path
    except Exception as exc:  # noqa: BLE001 - yt-dlp lança tipos variados
        raise DownloadError(f"Falha ao baixar o vídeo: {exc}") from exc
