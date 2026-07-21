"""Edição simples de um vídeo inteiro: marca d'água e/ou narração de
abertura, sem análise de IA e sem cortes.

Diferente do pipeline de Shorts (`src/core/pipeline.py`), que recorta,
reenquadra em 9:16 e aplica um preset de estilo em cada corte, aqui o vídeo
de origem é editado uma única vez, do início ao fim, mantendo resolução,
proporção e conteúdo original (a narração, quando usada, soma alguns
segundos no início).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.audio import tts
from src.utils import ffmpeg_utils
from src.utils.logger import get_logger
from src.video.branding import apply_tts_freeze_intro

logger = get_logger("simple_editor")

_MARGIN = 40  # px de respiro da marca d'água até a borda


@dataclass
class EditOptions:
    """Opções da edição, independentes do preset da página Estilo."""

    watermark_path: str = ""
    watermark_position: str = "top-right"
    watermark_size: int = 12         # % da largura do vídeo
    watermark_opacity: int = 70      # %
    music_path: str = ""
    music_volume: int = 20           # %
    narration_text: str = ""
    narration_voice: str = ""
    narration_position: str = "start"  # start | custom | end
    narration_time: float = 0.0        # segundos do vídeo (só quando "custom")


def has_edits(options: EditOptions) -> bool:
    """Indica se há algo de fato para aplicar (evita reencode à toa)."""
    watermark = bool(options.watermark_path and Path(options.watermark_path).exists())
    narration = bool(options.narration_text.strip())
    music = bool(options.music_path and Path(options.music_path).exists())
    return watermark or narration or music


def edit_video(
    source: str | Path,
    output_path: str | Path,
    options: EditOptions,
    workdir: Path,
    use_gpu: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Aplica marca d'água e/ou narração de abertura a um vídeo completo.

    Args:
        source: vídeo de origem (qualquer formato suportado pelo FFmpeg).
        output_path: MP4 final.
        options: marca d'água + narração desejadas.
        workdir: pasta temporária para o áudio da narração.
        use_gpu: tenta usar um encoder de GPU (NVENC/AMF) quando disponível.
        on_progress: callback opcional para mensagens de status.
    """
    source = Path(source)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def notify(message: str) -> None:
        logger.info(message)
        if on_progress:
            on_progress(message)

    info = ffmpeg_utils.video_info(source)
    graph = _base_graph(options, info["width"])

    if options.narration_text.strip():
        notify("Gerando narração...")
        tts_path = tts.synthesize(
            options.narration_text, options.narration_voice,
            workdir / "narracao.mp3",
        )
        if tts_path is not None:
            tts_seconds = tts.audio_duration(tts_path)
            at_seconds = _resolve_narration_time(options, info["duration"])
            graph = _insert_narration(graph, tts_path, tts_seconds, at_seconds, info["duration"])
        else:
            notify("Narração indisponível; seguindo sem ela.")

    notify("Renderizando vídeo editado...")
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
    notify("Edição concluída.")
    logger.info(
        "Vídeo editado exportado (%s): %s", "GPU" if gpu_args else "CPU", output_path,
    )
    return output_path


def _base_graph(options: EditOptions, video_width: int) -> str:
    """Grafo inicial [vout]/[aout]: marca d'água e/ou música de fundo, se houver."""
    parts: list[str] = []

    if options.watermark_path and Path(options.watermark_path).exists():
        wm_width = int(video_width * options.watermark_size / 100)
        wm_width -= wm_width % 2
        alpha = max(0.05, min(options.watermark_opacity / 100.0, 1.0))
        x, y = _corner_expr(options.watermark_position)
        parts.append(
            f"movie='{_escape_path(options.watermark_path)}',"
            f"scale={wm_width}:-1,format=rgba,colorchannelmixer=aa={alpha:.2f}[wm]"
        )
        parts.append(f"[0:v][wm]overlay={x}:{y}[vout]")
    else:
        if options.watermark_path:
            logger.warning("Marca d'água não encontrada: %s", options.watermark_path)
        parts.append("[0:v]null[vout]")

    if options.music_path and Path(options.music_path).exists():
        # loop=0 repete a música indefinidamente; duration=first no amix corta
        # o resultado na duração do áudio original (o vídeo), então se a
        # música for mais curta que o vídeo ela é completada com silêncio, e
        # se for mais longa, é cortada quando o vídeo termina.
        volume = max(0.0, min(options.music_volume / 100.0, 1.0))
        parts.append(
            f"amovie='{_escape_path(options.music_path)}':loop=0,"
            f"asetpts=N/SR/TB,aresample=48000,volume={volume:.2f}[bgm]"
        )
        parts.append(
            "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
    else:
        if options.music_path:
            logger.warning("Música de fundo não encontrada: %s", options.music_path)
        parts.append("[0:a]anull[aout]")

    return ";".join(parts)


def _resolve_narration_time(options: EditOptions, duration: float) -> float:
    """Segundo do vídeo onde a narração entra, conforme a posição escolhida."""
    if options.narration_position == "end":
        return duration
    if options.narration_position == "custom":
        return max(0.0, min(options.narration_time, duration))
    return 0.0  # "start"


def _insert_narration(
    graph: str, tts_path: Path, tts_seconds: float, at_seconds: float, duration: float,
) -> str:
    """Insere a narração no ponto `at_seconds` do vídeo.

    O vídeo congela no frame daquele instante enquanto a narração fala (evita
    dessincronizar fala e imagem); o corte fica `tts_seconds` mais longo.
    - `at_seconds` perto de 0: narração no início (congela o 1º frame).
    - `at_seconds` perto do fim: congela o último frame, sem retomar depois.
    - Caso contrário: parte o vídeo em dois, congela entre as partes.
    """
    if at_seconds <= 0.05:
        return apply_tts_freeze_intro(graph, tts_path, tts_seconds)

    graph = graph.replace("[vout]", "[vpre]").replace("[aout]", "[apre]")
    narration = (
        f";amovie='{_escape_path(tts_path)}',aresample=48000,apad,"
        f"atrim=duration={tts_seconds:.3f}[narr]"
    )
    if at_seconds >= duration - 0.05:
        return (
            graph
            + f";[vpre]tpad=stop_duration={tts_seconds:.3f}:stop_mode=clone[vout]"
            + narration
            + ";[apre][narr]concat=n=2:v=0:a=1[aout]"
        )

    t = f"{at_seconds:.3f}"
    return (
        graph
        + ";[vpre]split=2[vpa][vpb]"
        + f";[vpa]trim=0:{t},setpts=PTS-STARTPTS[va]"
        + f";[vpb]trim=start={t},setpts=PTS-STARTPTS[vb]"
        + f";[va]tpad=stop_duration={tts_seconds:.3f}:stop_mode=clone[vaext]"
        + ";[vaext][vb]concat=n=2:v=1:a=0[vout]"
        + ";[apre]asplit=2[apa][apb]"
        + f";[apa]atrim=0:{t},asetpts=PTS-STARTPTS[aa]"
        + f";[apb]atrim=start={t},asetpts=PTS-STARTPTS[ab]"
        + narration
        + ";[aa][narr][ab]concat=n=3:v=0:a=1[aout]"
    )


def _corner_expr(position: str) -> tuple[str, str]:
    """Expressões x/y do overlay para cada canto."""
    x = f"{_MARGIN}" if "left" in position else f"W-w-{_MARGIN}"
    y = f"{_MARGIN}" if "top" in position else f"H-h-{_MARGIN}"
    return x, y


def _escape_path(path: str | Path) -> str:
    """Escapa um caminho Windows para dentro de filtros FFmpeg."""
    return str(path).replace("\\", "/").replace(":", "\\:")
