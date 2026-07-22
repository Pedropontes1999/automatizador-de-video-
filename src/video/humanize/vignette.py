"""Vinheta extremamente leve (ponto 8): o filtro `vignette` do FFmpeg fica
mais forte quanto MENOR o ângulo (padrão "PI/5"); aqui o range fica sempre
perto de PI/2 (~sem vinheta nenhuma), só afastando um pouco conforme
`strength` sobe — nunca chega no padrão "forte" do filtro.
"""
from __future__ import annotations

import math

_MAX_ANGLE = math.pi / 2       # strength 0 -> quase impercetível
_MIN_ANGLE = math.pi / 3       # strength 1 -> ainda discreto (bem acima do
                                # padrão "PI/5" do FFmpeg, que fica forte
                                # demais em cenas já escuras)


def vignette_filter(strength: float) -> str:
    """`strength` em 0..1 (ver `params.py`, sorteado em 0.05-0.15 — sempre
    discreto)."""
    strength = max(0.0, min(strength, 1.0))
    angle = _MAX_ANGLE - strength * (_MAX_ANGLE - _MIN_ANGLE)
    return f"vignette=angle={angle:.4f}:mode=forward"
