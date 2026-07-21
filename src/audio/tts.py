"""Narração por IA usando vozes locais Piper (ONNX) — 100% offline.

Antes usava edge-tts (nuvem, Microsoft): uma chamada sem resposta travava o
pipeline inteiro sem aviso (já aconteceu), e cada trecho levava ~1-1.5s de
ida e volta pela rede — inviável em vídeos com centenas/milhares de trechos
(Redublagem). Piper roda local, sem rede, e é ~10x mais rápido por trecho.
"""
from __future__ import annotations

import threading
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from src.config.constants import PIPER_VOICES_DIR, TTS_DEFAULT_VOICE
from src.utils import ffmpeg_utils
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from piper import PiperVoice

logger = get_logger("tts")

_voices: dict[str, "PiperVoice"] = {}
_lock = threading.Lock()


def _load_voice(name: str) -> "PiperVoice":
    """Carrega (e cacheia) o modelo Piper; baixa da 1ª vez se precisar."""
    with _lock:
        cached = _voices.get(name)
        if cached is not None:
            return cached
        from piper import PiperVoice
        from piper.download_voices import download_voice

        model_path = PIPER_VOICES_DIR / f"{name}.onnx"
        if not model_path.exists():
            logger.info("Baixando voz '%s' (primeira vez, só um pouco de MB)...", name)
            PIPER_VOICES_DIR.mkdir(parents=True, exist_ok=True)
            download_voice(name, PIPER_VOICES_DIR)
        voice = PiperVoice.load(str(model_path))
        _voices[name] = voice
        return voice


def synthesize(text: str, voice: str, output_path: str | Path) -> Path | None:
    """Gera o áudio (WAV) da narração para o texto dado.

    Returns:
        Caminho do WAV gerado, ou None se a síntese falhou.
    """
    text = text.strip()
    if not text:
        return None
    output_path = Path(output_path).with_suffix(".wav")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        try:
            piper_voice = _load_voice(voice)
        except Exception as exc:  # noqa: BLE001 - voz inválida/sem rede na 1ª vez
            if voice == TTS_DEFAULT_VOICE:
                raise
            logger.warning(
                "Voz '%s' indisponível (%s); usando a padrão.", voice, exc,
            )
            piper_voice = _load_voice(TTS_DEFAULT_VOICE)
        with wave.open(str(output_path), "wb") as wav_file:
            piper_voice.synthesize_wav(text, wav_file)
    except ImportError:
        logger.error("Pacote piper-tts não instalado (pip install piper-tts).")
        return None
    except Exception as exc:  # noqa: BLE001 - nunca derrubar o pipeline por isso
        logger.warning("Narração indisponível (%s). Short sairá sem ela.", exc)
        return None
    if not output_path.exists() or output_path.stat().st_size == 0:
        logger.warning("Narração gerou arquivo vazio; ignorando.")
        return None
    logger.info("Narração gerada (%s): %s", voice, output_path.name)
    return output_path


def audio_duration(path: str | Path) -> float:
    """Duração de um arquivo de áudio em segundos (via ffprobe)."""
    data = ffmpeg_utils.probe(path)
    return float(data.get("format", {}).get("duration", 0.0))
