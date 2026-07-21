"""Corte manual de trechos de um vídeo (remoção de intervalos escolhidos
pelo usuário na aba Cortar Vídeo, com pré-visualização no próprio app).

Diferente do pipeline de Shorts (`src/core/pipeline.py`), aqui os intervalos
a remover são marcados manualmente, não pela IA: cada um é recortado fora e
o restante do vídeo é reconcatenado, mantendo áudio e vídeo sincronizados.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.utils import ffmpeg_utils
from src.utils.logger import get_logger

logger = get_logger("trim_editor")


@dataclass(frozen=True)
class CutRange:
    """Trecho do vídeo (em segundos) a remover."""

    start: float
    end: float


def merge_ranges(ranges: list[CutRange], duration: float) -> list[tuple[float, float]]:
    """Ordena, recorta aos limites do vídeo e funde intervalos sobrepostos."""
    clamped = sorted(
        (max(0.0, min(r.start, duration)), max(0.0, min(r.end, duration)))
        for r in ranges
        if r.end > r.start
    )
    merged: list[list[float]] = []
    for start, end in clamped:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def _segments_to_keep(cuts: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """Trechos que sobram depois de remover os cortes (complemento)."""
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in cuts:
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        keep.append((cursor, duration))
    return keep


def remove_ranges(
    source: str | Path,
    output_path: str | Path,
    ranges: list[CutRange],
    use_gpu: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Remove os trechos marcados e exporta o restante como um único MP4."""
    source = Path(source)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def notify(message: str) -> None:
        logger.info(message)
        if on_progress:
            on_progress(message)

    info = ffmpeg_utils.video_info(source)
    duration = info["duration"]
    cuts = merge_ranges(ranges, duration)
    if not cuts:
        raise ValueError("Nenhum corte válido para aplicar.")
    keep = _segments_to_keep(cuts, duration)
    if not keep:
        raise ValueError("Os cortes removem o vídeo inteiro.")

    notify(f"Removendo {len(cuts)} trecho(s)...")
    graph = _build_graph(keep)
    gpu_args = use_gpu and ffmpeg_utils.gpu_encoder_args(20)
    encoder_args = gpu_args or ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    ffmpeg_utils.run_ffmpeg([
        "-i", str(source),
        "-filter_complex", graph,
        "-map", "[vout]", "-map", "[aout]",
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path),
    ], timeout=7200)
    notify("Corte concluído.")
    logger.info(
        "Vídeo cortado (%s, %d trecho(s) removido(s)): %s",
        "GPU" if gpu_args else "CPU", len(cuts), output_path,
    )
    return output_path


def _build_graph(keep: list[tuple[float, float]]) -> str:
    """Grafo filter_complex: recorta cada trecho a manter e concatena."""
    parts: list[str] = []
    labels: list[str] = []
    for i, (start, end) in enumerate(keep):
        v, a = f"v{i}", f"a{i}"
        parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[{v}]")
        parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[{a}]")
        labels.append(f"[{v}][{a}]")
    parts.append(f"{''.join(labels)}concat=n={len(keep)}:v=1:a=1[vout][aout]")
    return ";".join(parts)
