"""Narração por IA usando XTTS v2 (Coqui) — local, offline, voz natural.

Pesado: cada trecho leva ~10-12s na CPU (sem GPU NVIDIA/CUDA disponível,
XTTS não acelera em AMD). Escolhido conscientemente pela qualidade da voz,
mesmo sabendo que isso torna a Redublagem de vídeos longos (centenas ou
milhares de trechos) uma etapa de horas. Trocado do Piper (rápido, mas
soava artificial demais) por pedido do usuário em 2026-07.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from src.config.constants import TTS_DEFAULT_VOICE
from src.utils import ffmpeg_utils
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from TTS.api import TTS as XttsApi

logger = get_logger("tts")

# A licença não-comercial do modelo XTTS é aceita automaticamente: o app é
# de uso pessoal/local, sem servir o modelo pra terceiros.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

_model: "XttsApi | None" = None
_lock = threading.Lock()


def _parse_voice(voice: str) -> tuple[str, str]:
    """Extrai (idioma, speaker) do id 'xtts:<idioma>:<speaker>'."""
    _, lang, speaker = voice.split(":", 2)
    return lang, speaker


def _load_model() -> "XttsApi":
    global _model
    with _lock:
        if _model is None:
            from TTS.api import TTS

            logger.info("Carregando modelo XTTS v2 (pode demorar na 1ª vez)...")
            _model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
        return _model


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
            lang, speaker = _parse_voice(voice)
        except ValueError:
            logger.warning("Voz '%s' inválida; usando a padrão.", voice)
            lang, speaker = _parse_voice(TTS_DEFAULT_VOICE)
        model = _load_model()
        model.tts_to_file(
            text=text, speaker=speaker, language=lang, file_path=str(output_path),
        )
    except ImportError:
        logger.error("Pacote coqui-tts não instalado (pip install coqui-tts[codec]).")
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
