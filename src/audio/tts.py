"""Narração por IA: dois motores, escolhidos pelo prefixo do id da voz.

- "xtts:<idioma>:<speaker>" — XTTS v2 (Coqui), local/offline, voz natural.
  Pesado: cada trecho leva ~10-12s na CPU (sem GPU NVIDIA/CUDA disponível,
  XTTS não acelera em AMD). Escolhido conscientemente pela qualidade da voz,
  mesmo sabendo que isso torna a Redublagem de vídeos longos (centenas ou
  milhares de trechos) uma etapa de horas. Trocado do Piper (rápido, mas
  soava artificial demais) por pedido do usuário em 2026-07. Suporta
  clonagem de voz via `voice_reference`.
- "edge:<nome curto da voz>" — Microsoft Edge TTS, nuvem, grátis, sem chave
  de API. Rápido e sem precisar de GPU, mas precisa de internet e não
  suporta clonagem de voz (`voice_reference` é ignorado). Adicionado por
  pedido do usuário em 2026-07 (voz "Antônio", grave e natural).
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

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

# Voz de fallback só pro engine XTTS (não usa TTS_DEFAULT_VOICE porque o
# padrão global pode ser uma voz "edge:...", formato incompatível aqui).
_XTTS_FALLBACK_VOICE = "xtts:pt:Xavier Hayasaka"


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


def _synthesize_xtts(
    text: str, voice: str, output_path: Path, voice_reference: str | Path | None,
) -> None:
    try:
        lang, speaker = _parse_voice(voice)
    except ValueError:
        logger.warning("Voz '%s' inválida; usando a padrão.", voice)
        lang, speaker = _parse_voice(_XTTS_FALLBACK_VOICE)
    model = _load_model()
    if voice_reference:
        model.tts_to_file(
            text=text, speaker_wav=str(voice_reference), language=lang,
            file_path=str(output_path),
        )
    else:
        model.tts_to_file(
            text=text, speaker=speaker, language=lang, file_path=str(output_path),
        )


def _synthesize_edge(text: str, edge_voice: str, output_path: Path) -> None:
    import edge_tts

    mp3_path = output_path.with_suffix(".edge.mp3")
    try:
        async def _run() -> None:
            await edge_tts.Communicate(text, edge_voice).save(str(mp3_path))

        asyncio.run(_run())
        if not mp3_path.exists() or mp3_path.stat().st_size == 0:
            raise RuntimeError("Edge TTS não retornou áudio.")
        # Recodifica pra WAV: o resto do pipeline (atempo, concat, mux)
        # espera sempre o mesmo formato, independente do motor de origem.
        ffmpeg_utils.run_ffmpeg(["-i", str(mp3_path), "-ar", "48000", "-ac", "2", str(output_path)])
    finally:
        mp3_path.unlink(missing_ok=True)


def synthesize(
    text: str, voice: str, output_path: str | Path,
    voice_reference: str | Path | None = None,
) -> Path | None:
    """Gera o áudio (WAV) da narração para o texto dado.

    Args:
        voice_reference: caminho de um áudio de referência (poucos segundos
            de fala limpa, sem música/ruído de fundo) para clonar essa voz
            em vez de usar um dos speakers prontos do XTTS — costuma soar
            bem mais natural. Só tem efeito com vozes "xtts:...": vozes
            "edge:..." ignoram esse parâmetro (a Microsoft não permite
            clonagem no Edge TTS).

    Returns:
        Caminho do WAV gerado, ou None se a síntese falhou.
    """
    text = text.strip()
    if not text:
        return None
    output_path = Path(output_path).with_suffix(".wav")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    engine, _, rest = voice.partition(":")
    try:
        if engine == "edge":
            _synthesize_edge(text, rest, output_path)
        else:
            _synthesize_xtts(text, voice, output_path, voice_reference)
    except ImportError:
        logger.error(
            "Pacote de narração não instalado (pip install coqui-tts[codec] "
            "ou pip install edge-tts, conforme a voz escolhida)."
        )
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
