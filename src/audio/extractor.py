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


def extract_audio_hq(
    video_path: str | Path, output_dir: str | Path, sample_rate: int = 48000,
) -> Path:
    """Extrai o áudio original em estéreo/alta taxa de amostragem.

    Usado quando o áudio também alimenta a separação de voz/música
    (Demucs), que perde qualidade com o WAV mono 16 kHz padrão do Whisper
    (o Whisper funciona igualmente bem com esse arquivo).
    """
    output = Path(output_dir) / "audio_hq.wav"
    run_ffmpeg([
        "-i", str(video_path),
        "-vn",
        "-ac", "2",
        "-ar", str(sample_rate),
        "-c:a", "pcm_s16le",
        str(output),
    ])
    logger.info("Áudio HQ extraído: %s", output)
    return output
