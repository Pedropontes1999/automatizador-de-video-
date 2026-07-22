"""Variação mínima de velocidade (ponto 5): só no vídeo, via `setpts` — o
áudio nunca é tocado (mapeado com `-c:a copy` no chamador), então o desvio
acumulado ao longo de um Short curto é irrelevante (~0.1s num vídeo de 60s
com o fator mais extremo do range abaixo)."""
from __future__ import annotations


def speed_filter(factor: float) -> str:
    """`factor` tipicamente em [0.998, 1.002] (ver `params.py`) — imperceptível."""
    return f"setpts=PTS/{factor:.4f}"
