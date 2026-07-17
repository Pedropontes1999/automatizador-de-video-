"""Exportação final dos Shorts (MP4 / H264 / AAC / 1080x1920).

Fluxo em duas etapas para máxima precisão:
1. `extract_segment` — recorta o trecho do vídeo original (re-encode rápido,
   preciso ao frame).
2. `export_short` — aplica no trecho: remoção de silêncios, reframe 9:16,
   efeitos, legendas queimadas e a cadeia de áudio, gerando o MP4 final.

Usa GPU (h264_nvenc) automaticamente quando disponível.
"""
from __future__ import annotations

from pathlib import Path

from src.utils.ffmpeg_utils import has_nvenc, run_ffmpeg
from src.utils.logger import get_logger

logger = get_logger("exporter")


def extract_segment(
    source: str | Path, start: float, end: float, output: str | Path,
) -> Path:
    """Recorta [start, end] do vídeo original com re-encode rápido e preciso."""
    output = Path(output)
    run_ffmpeg([
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        str(output),
    ])
    logger.info("Trecho extraído: %s (%.1fs)", output.name, end - start)
    return output


def _escape_filter_path(path: str | Path) -> str:
    """Escapa um caminho Windows para uso dentro de filtros FFmpeg (ass=...)."""
    return str(path).replace("\\", "/").replace(":", "\\:")


def _select_expression(keep: list[tuple[float, float]]) -> str:
    """Expressão select/aselect que mantém apenas os intervalos úteis."""
    return "+".join(f"between(t\\,{s:.3f}\\,{e:.3f})" for s, e in keep)


def build_filter_complex(
    reframe_filter: str,
    effect_filters: list[str],
    subtitle_path: Path | None,
    keep_intervals: list[tuple[float, float]] | None,
    audio_chain: str,
) -> str:
    """Monta o grafo -filter_complex completo (vídeo + áudio)."""
    video_parts: list[str] = []
    audio_parts: list[str] = []

    # 1) Remoção de silêncios/vícios: select mantém só os intervalos úteis
    #    e o setpts reconstrói os timestamps contínuos.
    if keep_intervals:
        expr = _select_expression(keep_intervals)
        video_parts.append(f"select='{expr}',setpts=N/FRAME_RATE/TB")
        audio_parts.append(f"aselect='{expr}',asetpts=N/SR/TB")

    # 2) Reframe 9:16 (pode conter subgrafo com ';' no modo fundo desfocado).
    video_parts.append(reframe_filter)

    # 3) Efeitos visuais.
    video_parts.extend(effect_filters)

    # 4) Legendas queimadas (arquivo .ass já remapeado para o tempo editado).
    if subtitle_path is not None:
        video_parts.append(f"ass='{_escape_filter_path(subtitle_path)}'")

    # 5) Cadeia de áudio (denoise/compressor/loudnorm/limiter).
    if audio_chain:
        audio_parts.append(audio_chain)

    video_graph = "[0:v]" + ",".join(video_parts) + "[vout]"
    audio_graph = "[0:a]" + (",".join(audio_parts) if audio_parts else "anull") + "[aout]"
    return f"{video_graph};{audio_graph}"


def export_short(
    segment_path: str | Path,
    output_path: str | Path,
    filter_complex: str,
    fps: int = 30,
    crf: int = 20,
    use_gpu: bool = True,
) -> Path:
    """Renderiza o Short final a partir do trecho extraído.

    Args:
        segment_path: trecho já recortado (saída de `extract_segment`).
        output_path: MP4 final.
        filter_complex: grafo montado por `build_filter_complex`.
        fps: quadros por segundo da saída.
        crf: qualidade x264 (menor = melhor).
        use_gpu: tenta usar h264_nvenc quando disponível.
    """
    output_path = Path(output_path)
    gpu = use_gpu and has_nvenc()
    if gpu:
        encoder_args = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(crf)]
    else:
        encoder_args = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]

    run_ffmpeg([
        "-i", str(segment_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        *encoder_args,
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path),
    ], timeout=1800)
    logger.info("Short exportado (%s): %s", "GPU" if gpu else "CPU", output_path)
    return output_path
