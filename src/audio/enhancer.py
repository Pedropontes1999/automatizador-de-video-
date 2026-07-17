"""Melhoria de áudio dos cortes: normalização, remoção de ruído,
compressão e limiter — tudo via filtros nativos do FFmpeg (gratuito).
"""
from __future__ import annotations

from src.utils.logger import get_logger

logger = get_logger("audio.enhancer")


def build_audio_filter_chain(
    normalize: bool = True,
    denoise: bool = True,
    compress: bool = True,
) -> str:
    """Monta a cadeia de filtros de áudio do FFmpeg para a exportação.

    Ordem correta da cadeia: denoise -> compressor -> loudnorm -> limiter.

    Returns:
        String para usar em `-af` (vazia se tudo desativado).
    """
    filters: list[str] = []
    if denoise:
        # afftdn: redução de ruído por FFT (nr = intensidade em dB).
        filters.append("afftdn=nr=12:nf=-30")
    if compress:
        # Compressor suave para uniformizar a voz.
        filters.append("acompressor=threshold=-18dB:ratio=3:attack=20:release=250")
    if normalize:
        # loudnorm no padrão de redes sociais (-14 LUFS).
        filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    # Limiter final: garante que nada estoure acima de -1 dB.
    filters.append("alimiter=limit=0.9")
    chain = ",".join(filters)
    logger.debug("Cadeia de filtros de áudio: %s", chain)
    return chain
