"""Correção de cor leve (ponto 6): alguns presets discretos, sorteado um por
renderização. Tudo num único filtro `eq` (sempre presente no FFmpeg, evita
depender de filtros extras como `colortemperature`/`colorbalance`).

"Sombras" e "temperatura" não são parâmetros nativos do `eq` — são
aproximados com `brightness` (leve, global) e um viés entre os canais de
gamma vermelho/azul (`gamma_r`/`gamma_b`), respectivamente.
"""
from __future__ import annotations

COLOR_PRESETS: dict[str, dict[str, float]] = {
    # Contraste +8%, Saturação +4%, Nitidez +10% (nitidez somada no sharpen.py)
    "A": {"contrast": 1.08, "saturation": 1.04},
    # Contraste +10%, Sombras -5% (aprox. via brightness leve), Nitidez +15%
    "B": {"contrast": 1.10, "brightness": -0.02},
    # Temperatura +2 (aprox. via gamma r/b), Saturação +6%, Contraste +5%
    "C": {"contrast": 1.05, "saturation": 1.06, "gamma_r": 1.02, "gamma_b": 0.98},
}

# Nitidez "de fábrica" de cada preset (soma com o slider de Nitidez, ver
# `sharpen.py`) — mantém a intenção original do preset mesmo se o usuário
# desligar o toggle de Nitidez separado.
PRESET_SHARPEN_BONUS: dict[str, float] = {"A": 0.10, "B": 0.15, "C": 0.08}


def color_filter(preset_name: str) -> str | None:
    """Filtro `eq=...` do preset, ou None se o nome não existir."""
    preset = COLOR_PRESETS.get(preset_name)
    if not preset:
        return None
    params = ":".join(f"{key}={value}" for key, value in preset.items())
    return f"eq={params}"
