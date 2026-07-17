"""Cálculo da nota final (0-100) de cada candidato a corte.

Combina as notas da IA por critério com um fator de duração ideal:
Shorts entre 30 e 60 segundos tendem a reter mais, então duração dentro
da faixa ideal recebe bônus e fora dela recebe penalidade suave.
"""
from __future__ import annotations

# Pesos de cada critério na nota final (somam 1.0).
_WEIGHTS: dict[str, float] = {
    "gancho": 0.22,
    "retencao": 0.20,
    "viral": 0.18,
    "engajamento": 0.15,
    "curiosidade": 0.15,
    "originalidade": 0.10,
}

_IDEAL_MIN = 30.0  # duração ideal mínima em segundos
_IDEAL_MAX = 60.0  # duração ideal máxima em segundos


def duration_factor(duration: float, min_dur: float, max_dur: float) -> float:
    """Fator multiplicador [0.7, 1.0] baseado na duração do corte."""
    if _IDEAL_MIN <= duration <= _IDEAL_MAX:
        return 1.0
    if duration < _IDEAL_MIN:
        # Penaliza proporcionalmente cortes muito curtos.
        span = max(_IDEAL_MIN - min_dur, 1.0)
        return max(0.7, 1.0 - 0.3 * (_IDEAL_MIN - duration) / span)
    span = max(max_dur - _IDEAL_MAX, 1.0)
    return max(0.7, 1.0 - 0.3 * (duration - _IDEAL_MAX) / span)


def compute_final_score(
    breakdown: dict[str, int],
    duration: float,
    min_dur: float,
    max_dur: float,
) -> int:
    """Nota final 0-100: média ponderada dos critérios x fator de duração."""
    weighted = sum(_WEIGHTS[k] * breakdown.get(k, 50) for k in _WEIGHTS)
    final = weighted * duration_factor(duration, min_dur, max_dur)
    return max(0, min(100, round(final)))
