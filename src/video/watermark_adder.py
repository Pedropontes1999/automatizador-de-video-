"""Aba Marca d'Água: cola uma imagem OU um texto por cima de um vídeo
inteiro, na posição escolhida — sem cortes nem passagem pelo pipeline de
análise por IA.

O oposto de `watermark_remover.py` (que apaga/cobre uma marca já existente).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.core.exceptions import AutoShortsError
from src.utils import ffmpeg_utils
from src.utils.logger import get_logger

logger = get_logger("watermark_adder")

_MARGIN = 40  # px de respiro até a borda


@dataclass
class WatermarkAddOptions:
    """Marca d'água a aplicar: imagem OU texto, nunca os dois."""

    mode: str = "image"              # "image" | "text"
    image_path: str = ""
    text: str = ""
    font_size: int = 48              # px (modo texto)
    position: str = "bottom-right"   # ver C.WATERMARK_POSITIONS
    size: int = 12                   # % da largura do vídeo (modo imagem)
    opacity: int = 70                # %


def add_watermark(
    source: str | Path,
    output_path: str | Path,
    options: WatermarkAddOptions,
    workdir: Path,
    use_gpu: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Aplica a marca d'água ao vídeo inteiro, mantendo o áudio original."""
    source = Path(source)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def notify(message: str) -> None:
        logger.info(message)
        if on_progress:
            on_progress(message)

    if options.mode == "text":
        graph = _text_graph(options, workdir / "marca_texto.txt")
    else:
        info = ffmpeg_utils.video_info(source)
        graph = _image_graph(options, info["width"])

    notify("Aplicando marca d'água...")
    gpu_args = use_gpu and ffmpeg_utils.gpu_encoder_args(20)
    encoder_args = gpu_args or ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    ffmpeg_utils.run_ffmpeg([
        "-i", str(source),
        "-filter_complex", graph,
        "-map", "[vout]", "-map", "0:a?",
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ], timeout=7200)
    notify("Marca d'água aplicada.")
    logger.info(
        "Marca d'água (%s, modo=%s) aplicada: %s",
        "GPU" if gpu_args else "CPU", options.mode, output_path,
    )
    return output_path


def _image_graph(options: WatermarkAddOptions, video_width: int) -> str:
    if not options.image_path or not Path(options.image_path).exists():
        raise AutoShortsError(f"Imagem da marca d'água não encontrada: {options.image_path}")
    wm_width = int(video_width * options.size / 100)
    wm_width -= wm_width % 2
    alpha = max(0.05, min(options.opacity / 100.0, 1.0))
    x, y = _corner_expr(options.position)
    return (
        f"movie='{_escape_path(options.image_path)}',"
        f"scale={wm_width}:-1,format=rgba,colorchannelmixer=aa={alpha:.2f}[wm]"
        f";[0:v][wm]overlay={x}:{y}[vout]"
    )


def _text_graph(options: WatermarkAddOptions, textfile: Path) -> str:
    text = options.text.strip()
    if not text:
        raise AutoShortsError("Texto da marca d'água está vazio.")
    font = _find_font()
    if font is None:
        raise AutoShortsError("Nenhuma fonte encontrada em C:/Windows/Fonts.")
    textfile.write_text(text, encoding="utf-8")
    alpha = max(0.05, min(options.opacity / 100.0, 1.0))
    x, y = _text_corner_expr(options.position)
    return (
        f"[0:v]drawtext=fontfile='{_escape_path(font)}':expansion=none"
        f":textfile='{_escape_path(textfile)}'"
        f":fontsize={options.font_size}:fontcolor=white@{alpha:.2f}"
        f":borderw=3:bordercolor=black@{alpha:.2f}"
        f":x={x}:y={y}[vout]"
    )


def _corner_expr(position: str) -> tuple[str, str]:
    """Expressões x/y do overlay (marca d'água em imagem): cada canto ou centro."""
    if position == "center":
        return "(W-w)/2", "(H-h)/2"
    x = f"{_MARGIN}" if "left" in position else f"W-w-{_MARGIN}"
    y = f"{_MARGIN}" if "top" in position else f"H-h-{_MARGIN}"
    return x, y


def _text_corner_expr(position: str) -> tuple[str, str]:
    """Expressões x/y do drawtext (marca d'água em texto): cada canto ou centro."""
    if position == "center":
        return "(w-text_w)/2", "(h-text_h)/2"
    x = f"{_MARGIN}" if "left" in position else f"w-text_w-{_MARGIN}"
    y = f"{_MARGIN}" if "top" in position else f"h-text_h-{_MARGIN}"
    return x, y


def _escape_path(path: str | Path) -> str:
    """Escapa um caminho Windows para dentro de filtros FFmpeg."""
    return str(path).replace("\\", "/").replace(":", "\\:")


def _find_font() -> str | None:
    """Fonte em negrito do Windows para o texto queimado no vídeo."""
    for name in ("arialbd.ttf", "arial.ttf", "impact.ttf", "seguisb.ttf"):
        candidate = Path("C:/Windows/Fonts") / name
        if candidate.exists():
            return str(candidate)
    return None
