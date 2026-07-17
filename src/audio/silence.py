"""Detecção de silêncios, pausas e trechos removíveis.

Usa o filtro `silencedetect` do FFmpeg para localizar silêncios no corte e o
texto da transcrição para localizar vícios de linguagem ("ãh", "éh"...).
As janelas detectadas são removidas na exportação (via select/aselect).
"""
from __future__ import annotations

import re
from pathlib import Path

from src.config.constants import (
    FILLER_WORDS_PT,
    MIN_SILENCE_SECONDS,
    SILENCE_THRESHOLD_DB,
)
from src.models.domain import TranscriptSegment
from src.utils.ffmpeg_utils import find_binary
from src.utils.logger import get_logger

import subprocess
import sys

logger = get_logger("audio.silence")

_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_SILENCE_RE = re.compile(r"silence_start: (?P<start>[\d.]+)|silence_end: (?P<end>[\d.]+)")


def detect_silences(
    media_path: str | Path,
    threshold_db: float = SILENCE_THRESHOLD_DB,
    min_duration: float = MIN_SILENCE_SECONDS,
) -> list[tuple[float, float]]:
    """Detecta janelas de silêncio (start, end) em segundos no arquivo."""
    cmd = [
        find_binary("ffmpeg"), "-hide_banner", "-i", str(media_path),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_CREATION_FLAGS,
    )
    silences: list[tuple[float, float]] = []
    current_start: float | None = None
    for match in _SILENCE_RE.finditer(result.stderr):
        if match.group("start") is not None:
            current_start = float(match.group("start"))
        elif match.group("end") is not None and current_start is not None:
            silences.append((current_start, float(match.group("end"))))
            current_start = None
    logger.info("Silêncios detectados: %d", len(silences))
    return silences


def find_filler_segments(
    segments: list[TranscriptSegment],
    fillers: tuple[str, ...] = FILLER_WORDS_PT,
) -> list[tuple[float, float]]:
    """Localiza palavras de preenchimento isoladas ("ãh", "éh") via transcrição."""
    windows: list[tuple[float, float]] = []
    filler_set = {f.lower() for f in fillers}
    for seg in segments:
        for word in seg.words:
            clean = word.text.lower().strip(".,!?… ")
            if clean in filler_set and (word.end - word.start) >= 0.25:
                windows.append((word.start, word.end))
    logger.info("Vícios de linguagem detectados: %d", len(windows))
    return windows


def merge_windows(
    windows: list[tuple[float, float]], gap: float = 0.05,
) -> list[tuple[float, float]]:
    """Une janelas sobrepostas/adjacentes em uma lista ordenada."""
    if not windows:
        return []
    ordered = sorted(windows)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def keep_intervals(
    remove: list[tuple[float, float]], total_start: float, total_end: float,
    padding: float = 0.12,
) -> list[tuple[float, float]]:
    """Inverte janelas de remoção em intervalos a MANTER dentro do corte.

    `padding` preserva uma pequena folga nas bordas para evitar cortes secos.
    """
    keep: list[tuple[float, float]] = []
    cursor = total_start
    for start, end in merge_windows(remove):
        # Encolhe a janela removida pelo padding.
        start, end = start + padding, end - padding
        if end <= start:
            continue
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total_end:
        keep.append((cursor, total_end))
    # Descarta migalhas menores que 200 ms.
    return [(s, e) for s, e in keep if e - s > 0.2]
