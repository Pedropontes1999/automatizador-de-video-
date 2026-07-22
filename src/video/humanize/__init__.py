"""Modo Humanizado: pequenas variações automáticas e sorteadas (zoom, pan,
reenquadramento inteligente, cor, nitidez, espelhamento parcial, vinheta,
granulado, variação de velocidade) aplicadas na aba Editar Shorts, pra que
duas exportações do mesmo vídeo nunca fiquem tecnicamente idênticas.

Cada sub-efeito vive no seu próprio módulo (zoom_pan, color, sharpen,
vignette, grain, mirror, speed); `params.py` sorteia os parâmetros de uma
renderização e `pipeline.py` orquestra tudo numa única cadeia de filtros.
"""
from __future__ import annotations

from src.video.humanize.params import HumanizeParams, HumanizeToggles
from src.video.humanize.pipeline import build_humanize_video_filter

__all__ = ["HumanizeParams", "HumanizeToggles", "build_humanize_video_filter"]
