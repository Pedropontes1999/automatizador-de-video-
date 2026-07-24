"""Narração por IA via ElevenLabs (nuvem, paga; chave em
`Settings.elevenlabs_api_key`).

Motor único por escolha do usuário em 2026-07 ao assinar um plano pago —
os motores anteriores (Piper, XTTS v2/Coqui, Microsoft Edge TTS) foram
removidos, não só desativados. Fixada em uma única voz da conta do usuário
(ver `TTS_VOICES`).
"""
from __future__ import annotations

from pathlib import Path

import requests

from src.config import constants as C
from src.utils import ffmpeg_utils
from src.utils.logger import get_logger

logger = get_logger("tts")


def _synthesize_elevenlabs(text: str, voice_id: str, api_key: str, output_path: Path) -> None:
    if not api_key:
        raise RuntimeError("Chave de API da ElevenLabs não configurada (Configurações).")
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": api_key, "Accept": "audio/mpeg"},
        json={
            "text": text,
            "model_id": C.ELEVENLABS_MODEL_ID,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60,
    )
    if resp.status_code == 401:
        raise RuntimeError("Chave de API da ElevenLabs inválida/expirada.")
    resp.raise_for_status()
    mp3_path = output_path.with_suffix(".eleven.mp3")
    try:
        mp3_path.write_bytes(resp.content)
        # Recodifica pra WAV: o resto do pipeline (atempo, concat, mux)
        # espera sempre o mesmo formato.
        ffmpeg_utils.run_ffmpeg(["-i", str(mp3_path), "-ar", "48000", "-ac", "2", str(output_path)])
    finally:
        mp3_path.unlink(missing_ok=True)


def synthesize(
    text: str, voice: str, output_path: str | Path, api_key: str = "",
) -> Path | None:
    """Gera o áudio (WAV) da narração para o texto dado via ElevenLabs.

    Args:
        api_key: chave de API da ElevenLabs (`Settings.elevenlabs_api_key`).

    Returns:
        Caminho do WAV gerado, ou None se a síntese falhou.
    """
    text = text.strip()
    if not text:
        return None
    output_path = Path(output_path).with_suffix(".wav")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _, _, voice_id = voice.partition(":")
    try:
        _synthesize_elevenlabs(text, voice_id, api_key, output_path)
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
