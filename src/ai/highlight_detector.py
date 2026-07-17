"""Detecção de momentos de "hype" por picos de energia no áudio.

Complementa a análise por transcrição (Ollama) em conteúdos onde os melhores
momentos não estão na fala — lutas de anime, jogadas de game, arrancadas de
carro. Cenas de ação vêm acompanhadas de explosões, trilha sonora alta e
gritos, que aparecem como picos sustentados de energia RMS no áudio.

100% local e leve: lê o WAV 16 kHz mono já extraído pelo pipeline.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from src.models.domain import CutCandidate
from src.utils.logger import get_logger

logger = get_logger("highlight_detector")

_WINDOW_SECONDS = 0.25   # resolução da curva de energia
_SMOOTH_SECONDS = 2.0    # média móvel: ignora estouros instantâneos (porta batendo)
_PEAK_PERCENTILE = 88.0  # energia acima deste percentil conta como "hype"
_MERGE_GAP_SECONDS = 3.0  # junta regiões de pico separadas por menos que isso
_MIN_REGION_SECONDS = 1.0  # descarta picos mais curtos que isso
_LEAD_IN_SECONDS = 4.0   # contexto antes do pico (vira o gancho do Short)


def detect_audio_highlights(
    audio_path: str | Path,
    min_duration: float,
    max_duration: float,
    max_candidates: int = 8,
) -> list[CutCandidate]:
    """Encontra janelas de alta intensidade sonora e devolve candidatos a corte.

    Args:
        audio_path: WAV 16 kHz mono (o mesmo usado pelo Whisper).
        min_duration/max_duration: limites de duração de cada corte.
        max_candidates: máximo de candidatos devolvidos.
    """
    try:
        rms = _energy_curve(Path(audio_path))
    except (wave.Error, OSError, EOFError, ValueError) as exc:
        logger.warning("Falha ao ler áudio para detecção de picos: %s", exc)
        return []

    hop = _WINDOW_SECONDS
    total = len(rms) * hop
    if total < min_duration:
        return []

    kernel = max(int(_SMOOTH_SECONDS / hop), 1)
    smooth = np.convolve(rms, np.ones(kernel) / kernel, mode="same")

    baseline = float(np.median(smooth))
    threshold = float(np.percentile(smooth, _PEAK_PERCENTILE))
    if threshold <= baseline * 1.05:
        # Áudio praticamente uniforme (ex.: música constante do início ao
        # fim): não há picos que se destaquem do resto.
        logger.info("Energia do áudio uniforme — nenhum pico de ação destacado.")
        return []

    regions = _regions_above(smooth, threshold, hop)
    peak_max = float(smooth.max())
    candidates: list[CutCandidate] = []
    for start_idx, end_idx in regions:
        peak = float(smooth[start_idx:end_idx].max())
        prominence = (peak - baseline) / max(peak_max - baseline, 1e-6)
        region_start = start_idx * hop
        region_len = (end_idx - start_idx) * hop
        # A janela cobre a região de pico com folga antes (gancho) e depois.
        duration = min(max(region_len + _LEAD_IN_SECONDS + 6.0, min_duration), max_duration)
        start = max(region_start - _LEAD_IN_SECONDS, 0.0)
        if start + duration > total:
            start = max(total - duration, 0.0)
        candidates.append(CutCandidate(
            start=round(start, 2),
            end=round(min(start + duration, total), 2),
            title=f"Cena de ação {_fmt_ts(region_start)}",
            description="Momento de alta intensidade detectado pelo áudio.",
            hashtags=["#shorts", "#edit", "#hype"],
            category="acao",
            score=int(round(55 + 35 * prominence)),
            reason=(
                "Pico sustentado de energia sonora (trilha alta, gritos ou "
                "efeitos) — típico de cena de ação/hype."
            ),
        ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    kept: list[CutCandidate] = []
    for cand in candidates:
        overlaps = any(
            min(cand.end, k.end) - max(cand.start, k.start) > 0.5 * cand.duration
            for k in kept
        )
        if not overlaps:
            kept.append(cand)
        if len(kept) >= max_candidates:
            break
    logger.info(
        "Picos de áudio: %d regiões detectadas, %d candidatos finais.",
        len(regions), len(kept),
    )
    return kept


# --------------------------------------------------------------------------- #
def _energy_curve(audio_path: Path) -> np.ndarray:
    """Energia RMS por janela de _WINDOW_SECONDS do WAV mono."""
    with wave.open(str(audio_path), "rb") as wav:
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(rate * _WINDOW_SECONDS)
    usable = len(samples) - (len(samples) % hop)
    if usable < hop:
        return np.array([], dtype=np.float32)
    windows = samples[:usable].reshape(-1, hop)
    return np.sqrt(np.mean(windows * windows, axis=1))


def _regions_above(
    smooth: np.ndarray, threshold: float, hop: float,
) -> list[tuple[int, int]]:
    """Regiões contíguas [início, fim) acima do limiar, mescladas e filtradas."""
    regions: list[list[int]] = []
    start: int | None = None
    for i, flag in enumerate(smooth >= threshold):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            regions.append([start, i])
            start = None
    if start is not None:
        regions.append([start, len(smooth)])

    gap = int(_MERGE_GAP_SECONDS / hop)
    merged: list[list[int]] = []
    for reg in regions:
        if merged and reg[0] - merged[-1][1] <= gap:
            merged[-1][1] = reg[1]
        else:
            merged.append(reg)
    min_len = max(int(_MIN_REGION_SECONDS / hop), 1)
    return [(a, b) for a, b in merged if b - a >= min_len]


def _fmt_ts(seconds: float) -> str:
    """Formata segundos como "12m35s" (usado no título/nome do arquivo)."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}m{s:02d}s"
