"""Granulado cinematográfico leve (ponto 9): 2-4% via o filtro `noise`."""
from __future__ import annotations

_STRENGTH_SCALE = 3.0  # mapeia a % (2-4) pra escala 0-100 do `noise`, mantendo sutil


def grain_filter(amount_percent: float) -> str:
    """`amount_percent` tipicamente 2..4 (ver `params.py`)."""
    strength = max(0, min(round(amount_percent * _STRENGTH_SCALE), 100))
    return f"noise=alls={strength}:allf=t"
