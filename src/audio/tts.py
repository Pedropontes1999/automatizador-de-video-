"""Narração por IA usando as vozes neurais da Microsoft (edge-tts).

Única etapa do pipeline que precisa de internet. Uma falha aqui (offline,
serviço fora do ar) nunca derruba o processamento: o short apenas sai sem
narração, com aviso no log.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from src.utils import ffmpeg_utils
from src.utils.logger import get_logger

logger = get_logger("tts")


def synthesize(text: str, voice: str, output_path: str | Path) -> Path | None:
    """Gera o áudio da narração (MP3) para o texto dado.

    Returns:
        Caminho do MP3 gerado, ou None se a síntese falhou.
    """
    text = text.strip()
    if not text:
        return None
    output_path = Path(output_path)
    try:
        import edge_tts

        async def _run() -> None:
            await edge_tts.Communicate(text, voice).save(str(output_path))

        asyncio.run(_run())
    except ImportError:
        logger.error("Pacote edge-tts não instalado (pip install edge-tts).")
        return None
    except Exception as exc:  # noqa: BLE001 - rede/serviço fora do nosso controle
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
