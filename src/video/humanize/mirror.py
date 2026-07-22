"""Espelhamento horizontal parcial (ponto 4): só numa janela curta e
aleatória do vídeo — nunca o vídeo inteiro."""
from __future__ import annotations


def mirror_filter(scene: tuple[float, float] | None) -> str | None:
    """Filtro `hflip` com `enable` restrito a `[scene]`, ou None se não
    houver cena sorteada (probabilidade configurável, ver `params.py`)."""
    if scene is None:
        return None
    start, end = scene
    return f"hflip=enable='between(t\\,{start:.3f}\\,{end:.3f})'"
