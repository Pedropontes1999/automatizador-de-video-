"""Wrapper fino sobre o FFmpeg/FFprobe.

Todas as chamadas ao FFmpeg do projeto passam por aqui, garantindo:
- Detecção do binário (PATH ou pasta local);
- Execução sem janelas de console no Windows;
- Erros convertidos em exceções claras (`FFmpegError`).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from src.core.exceptions import FFmpegError
from src.utils.logger import get_logger

logger = get_logger("ffmpeg")

# No Windows, esconde a janela de console dos subprocessos.
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _winget_ffmpeg_dir() -> Path | None:
    """Localiza a pasta bin/ do FFmpeg instalado pelo winget (Gyan.FFmpeg).

    Necessário porque processos abertos antes da instalação (ou via duplo
    clique) podem não ter o PATH atualizado pelo Windows.
    """
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if not base.exists():
        return None
    for package in base.glob("Gyan.FFmpeg*"):
        for exe in package.glob("**/bin/ffmpeg.exe"):
            return exe.parent
    return None


def get_ffmpeg_dir() -> Path | None:
    """Pasta que contém o ffmpeg.exe (PATH, pasta bin/ local ou winget)."""
    found = shutil.which("ffmpeg")
    if found:
        return Path(found).parent
    local = Path(__file__).resolve().parents[2] / "bin"
    if (local / "ffmpeg.exe").exists():
        return local
    return _winget_ffmpeg_dir()


def ensure_ffmpeg_in_path() -> None:
    """Garante que o FFmpeg esteja no PATH do processo (chamado no startup).

    Assim yt-dlp, moviepy e qualquer subprocesso encontram o binário mesmo
    quando a aplicação foi aberta sem o PATH atualizado do sistema.
    """
    if shutil.which("ffmpeg"):
        return
    ffmpeg_dir = get_ffmpeg_dir()
    if ffmpeg_dir is not None:
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
        logger.info("FFmpeg adicionado ao PATH do processo: %s", ffmpeg_dir)


def find_binary(name: str) -> str:
    """Localiza ffmpeg/ffprobe no PATH, na pasta bin/ local ou no winget."""
    found = shutil.which(name)
    if found:
        return found
    for folder in filter(None, (get_ffmpeg_dir(),)):
        candidate = folder / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
    raise FFmpegError(
        f"'{name}' não encontrado. Instale o FFmpeg e adicione ao PATH "
        "(https://ffmpeg.org) ou coloque o executável na pasta bin/."
    )


def run_ffmpeg(args: list[str], timeout: int | None = None) -> str:
    """Executa `ffmpeg -y -hide_banner <args>` e retorna o stderr (progresso)."""
    cmd = [find_binary("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", *args]
    logger.debug("FFmpeg: %s", " ".join(cmd))
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_CREATION_FLAGS,
    )
    if result.returncode != 0:
        raise FFmpegError(f"FFmpeg falhou ({result.returncode}): {result.stderr[-800:]}")
    return result.stderr


def probe(video_path: str | Path) -> dict:
    """Retorna metadados do vídeo via ffprobe (formato + streams, JSON)."""
    cmd = [
        find_binary("ffprobe"), "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_CREATION_FLAGS,
    )
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe falhou para {video_path}: {result.stderr[-400:]}")
    return json.loads(result.stdout)


def video_info(video_path: str | Path) -> dict:
    """Extrai informações essenciais: duração, resolução, fps."""
    data = probe(video_path)
    stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None,
    )
    if stream is None:
        raise FFmpegError(f"Nenhum stream de vídeo em {video_path}")
    num, _, den = (stream.get("r_frame_rate", "30/1")).partition("/")
    fps = float(num) / float(den or 1)
    return {
        "duration": float(data.get("format", {}).get("duration", 0.0)),
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "fps": fps,
    }


_nvenc_available: bool | None = None  # cache do teste funcional


def has_nvenc() -> bool:
    """Verifica se o encoder NVIDIA h264_nvenc realmente FUNCIONA.

    Listar encoders não basta: o FFmpeg pode ter o nvenc compilado mesmo em
    máquinas sem GPU NVIDIA (falharia com 'Could not open encoder'). Por isso
    é feito um teste real codificando alguns frames sintéticos (resultado é
    cacheado no processo).
    """
    global _nvenc_available
    if _nvenc_available is not None:
        return _nvenc_available
    try:
        result = subprocess.run(
            [
                find_binary("ffmpeg"), "-hide_banner", "-v", "error",
                "-f", "lavfi", "-i", "nullsrc=s=256x256:r=10:d=0.3",
                "-frames:v", "3", "-c:v", "h264_nvenc", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=30,
            creationflags=_CREATION_FLAGS,
        )
        _nvenc_available = result.returncode == 0
    except (FFmpegError, OSError, subprocess.TimeoutExpired):
        _nvenc_available = False
    logger.info(
        "Encoder de GPU (h264_nvenc): %s",
        "disponível" if _nvenc_available else "indisponível — usando CPU (libx264)",
    )
    return _nvenc_available
