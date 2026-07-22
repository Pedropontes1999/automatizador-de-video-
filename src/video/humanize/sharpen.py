"""Nitidez leve (ponto 7): `unsharp` com força limitada pra nunca exagerar."""
from __future__ import annotations

_MAX_LUMA_AMOUNT = 1.2  # bem abaixo do default "forte" do unsharp (2.0)


def sharpen_filter(amount: float) -> str:
    """`amount` em 0..1 (ver `params.py`), mapeado pra uma faixa sutil do
    `unsharp`."""
    luma_amount = max(0.0, min(amount, 1.0)) * _MAX_LUMA_AMOUNT
    return f"unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount={luma_amount:.3f}"
