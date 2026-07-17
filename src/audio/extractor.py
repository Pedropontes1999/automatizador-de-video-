"""Extração de áudio do vídeo (etapa 1 do pipeline).

Gera WAV mono 16 kHz — o formato ideal para o Whisper.
"""
from __future__ import annotations

from pathlib import Path

from src.utils.ffmpeg_utils import run_ffmpeg
from src.utils.logger import get_logger

logger = get_logger("audio.extractor")


def extract_audio(video_path: str | Path, output_dir: str | Path) -> Path:
    """Extrai o áudio do vídeo como WAV 16 kHz mono.

    Args:
        video_path: vídeo de origem.
        output_dir: pasta onde o WAV será salvo.

    Returns:
        Caminho do arquivo de áudio gerado.
    """
    output = Path(output_dir) / "audio_16k.wav"
    run_ffmpeg([
        "-i", str(video_path),
        "-vn",                    # sem vídeo
        "-ac", "1",               # mono
        "-ar", "16000",           # 16 kHz (padrão Whisper)
        "-c:a", "pcm_s16le",      # WAV sem compressão
        str(output),
    ])
    logger.info("Áudio extraído: %s", output)
    return output
