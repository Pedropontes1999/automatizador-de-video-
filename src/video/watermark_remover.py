"""Remoção/cobertura de marca d'água estática (aba Remover Marca d'Água).

Recorta um frame do vídeo pra o usuário marcar a área da marca d'água na
GUI, e oferece dois métodos pra tratar essa área, quadro a quadro:

- `remove_watermark`: reconstrói a área com o filtro `delogo` do FFmpeg, a
  partir dos pixels ao redor. Funciona bem quando a marca fica sempre na
  mesma posição (caso comum de selos de canal) e o fundo atrás dela é
  relativamente liso; fundos muito detalhados/com movimento rápido atrás da
  marca podem deixar um leve borrão visível.
- `cover_watermark`: cola uma imagem (ex.: o logo do seu canal) exatamente
  em cima da área marcada, sem tentar reconstruir nada — mais confiável em
  fundos complexos, desde que a imagem cubra a área por completo.
- `remove_and_cover_watermark`: os dois em sequência, numa única passada —
  apaga a marca original com `delogo` e cola a nova imagem por cima do
  resultado. Essencial quando a imagem de cobertura tem fundo transparente
  (ex.: só um texto/logo): sem apagar antes, a marca antiga continua
  visível ao redor das letras novas.
- `blur_watermark`: borra só a área marcada (o resto do frame continua
  nítido) — opção mais simples quando não faz sentido reconstruir o fundo
  nem colar imagem/texto nenhum por cima.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.core.exceptions import AutoShortsError
from src.utils import ffmpeg_utils
from src.utils.logger import get_logger

logger = get_logger("watermark_remover")

_MIN_SIZE = 2  # menor largura/altura aceita pelo filtro `delogo`


@dataclass(frozen=True)
class WatermarkRegion:
    """Retângulo (em pixels, coordenadas do vídeo original) sobre a marca."""

    x: int
    y: int
    w: int
    h: int

    def clamp(self, frame_w: int, frame_h: int) -> "WatermarkRegion":
        """Garante que o retângulo cabe dentro do frame.

        O filtro `delogo` exige pelo menos 1px de margem em TODAS as bordas
        — `x`/`y` não podem ser 0 (encostar no topo/esquerda) nem `x+w`/`y+h`
        podem alcançar a largura/altura (encostar embaixo/direita) — testado
        empiricamente, já que o próprio FFmpeg não documenta essa exigência.
        Marca d'água costuma ficar bem num canto, então sem essa margem
        reservada, marcar rente à borda derrubava o filtro com "Logo area is
        outside of the frame".
        """
        max_w = max(frame_w - 1, _MIN_SIZE + 1)
        max_h = max(frame_h - 1, _MIN_SIZE + 1)
        x = max(1, min(self.x, max_w - _MIN_SIZE))
        y = max(1, min(self.y, max_h - _MIN_SIZE))
        w = max(_MIN_SIZE, min(self.w, max_w - x))
        h = max(_MIN_SIZE, min(self.h, max_h - y))
        return WatermarkRegion(x, y, w, h)


def extract_frame(
    video_path: str | Path, timestamp: float, output_path: str | Path,
) -> Path:
    """Extrai um único frame do vídeo (PNG) no instante `timestamp` (s), pra
    o usuário marcar a área da marca d'água em cima dele na GUI."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_utils.run_ffmpeg([
        "-ss", f"{max(timestamp, 0.0):.3f}", "-i", str(video_path),
        "-frames:v", "1", str(output_path),
    ])
    if not output_path.exists() or output_path.stat().st_size == 0:
        # -ss em cima ou além do fim do vídeo não dá erro no FFmpeg, só não
        # escreve frame nenhum — sem essa checagem, o resto do fluxo seguia
        # achando que tinha um frame válido carregado.
        raise AutoShortsError(
            f"Não foi possível capturar um frame em {timestamp:.1f}s "
            "(esse instante pode estar além da duração do vídeo)."
        )
    return output_path


def render_text_cover(text: str, width: int, height: int, output_path: str | Path) -> Path:
    """Gera um PNG transparente com `text` centralizado, do tamanho exato da
    área marcada — usado como cobertura no lugar de uma imagem própria (ver
    `remove_and_cover_watermark`), pra quem quer digitar o que vai por cima
    da marca em vez de escolher um logo/imagem pronta."""
    from PIL import Image, ImageDraw, ImageFont

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = max(width, 1), max(height, 1)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font_path = _find_system_font()
    margin = max(2, min(width, height) // 20)
    max_w, max_h = width - 2 * margin, height - 2 * margin

    font_size = height
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    if font_path:
        while font_size > 6:
            font = ImageFont.truetype(font_path, font_size)
            stroke_w = max(1, font_size // 20)
            box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
            if box[2] - box[0] <= max_w and box[3] - box[1] <= max_h:
                break
            font_size -= 2

    stroke_w = max(1, font_size // 20)
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    x = (width - (box[2] - box[0])) / 2 - box[0]
    y = (height - (box[3] - box[1])) / 2 - box[1]
    draw.text(
        (x, y), text, font=font, fill=(255, 255, 255, 255),
        stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255),
    )
    image.save(output_path)
    return output_path


def _find_system_font() -> str | None:
    """Fonte em negrito do Windows pra desenhar o texto de cobertura."""
    for name in ("arialbd.ttf", "arial.ttf", "impact.ttf", "seguisb.ttf"):
        candidate = Path("C:/Windows/Fonts") / name
        if candidate.exists():
            return str(candidate)
    return None


def resolve_frame_size(source: Path, frame_size: tuple[int, int] | None) -> tuple[int, int]:
    """Resolve a dimensão do frame pra encaixar a área marcada.

    Sempre que disponível, usa a dimensão que a GUI viu de fato (ver
    `FrameRectSelector.frame_size`) em vez do `ffprobe`: em vídeos com
    metadado de rotação, o ffprobe reporta a resolução "crua" (antes de
    rotacionar), diferente do frame que o usuário marcou — usar a resolução
    errada faz o `delogo`/overlay recusar a área como "fora do frame".
    """
    if frame_size is not None:
        return frame_size
    info = ffmpeg_utils.video_info(source)
    return info["width"], info["height"]


def remove_watermark(
    source: str | Path,
    output_path: str | Path,
    region: WatermarkRegion,
    use_gpu: bool = True,
    crf: int = 20,
    frame_size: tuple[int, int] | None = None,
    on_progress: Callable[[str], None] | None = None,
    extra_filters: str | None = None,
) -> Path:
    """Remove a marca d'água estática da área marcada e reexporta o vídeo
    (áudio mantido sem reencode).

    `extra_filters` (opcional) é uma cadeia de filtros adicional aplicada
    logo em seguida, na mesma passada — usado pelo Modo Humanizado pra não
    precisar reencodar o vídeo duas vezes."""
    source = Path(source)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def notify(message: str) -> None:
        logger.info(message)
        if on_progress:
            on_progress(message)

    frame_w, frame_h = resolve_frame_size(source, frame_size)
    rect = region.clamp(frame_w, frame_h)

    notify("Removendo marca d'água...")
    gpu_args = use_gpu and ffmpeg_utils.gpu_encoder_args(crf)
    encoder_args = gpu_args or ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
    vf = f"delogo=x={rect.x}:y={rect.y}:w={rect.w}:h={rect.h}:show=0"
    if extra_filters:
        vf = f"{vf},{extra_filters}"
    ffmpeg_utils.run_ffmpeg([
        "-i", str(source),
        "-vf", vf,
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ], timeout=7200)
    notify("Marca d'água removida.")
    logger.info(
        "Marca d'água removida (%s, área %dx%d @ %d,%d): %s",
        "GPU" if gpu_args else "CPU", rect.w, rect.h, rect.x, rect.y, output_path,
    )
    return output_path


def blur_watermark(
    source: str | Path,
    output_path: str | Path,
    region: WatermarkRegion,
    strength: int = 25,
    use_gpu: bool = True,
    crf: int = 20,
    frame_size: tuple[int, int] | None = None,
    on_progress: Callable[[str], None] | None = None,
    extra_filters: str | None = None,
) -> Path:
    """Borra a área marcada (sem reconstruir nem colar nada por cima) e
    reexporta o vídeo (áudio mantido sem reencode).

    `strength` é o sigma do `gblur` — não usa o `region.clamp` do `delogo`
    (que exige margem nas bordas) porque `crop`+`gblur` não tem essa
    exigência; a marca costuma ficar bem num canto, então essa margem só
    encolheria a área à toa.

    `extra_filters` (opcional): ver `remove_watermark`.
    """
    source = Path(source)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def notify(message: str) -> None:
        logger.info(message)
        if on_progress:
            on_progress(message)

    frame_w, frame_h = resolve_frame_size(source, frame_size)
    x = max(0, min(region.x, frame_w - _MIN_SIZE))
    y = max(0, min(region.y, frame_h - _MIN_SIZE))
    w = max(_MIN_SIZE, min(region.w, frame_w - x))
    h = max(_MIN_SIZE, min(region.h, frame_h - y))

    notify("Borrando marca d'água...")
    gpu_args = use_gpu and ffmpeg_utils.gpu_encoder_args(crf)
    encoder_args = gpu_args or ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
    final_label = "merged" if extra_filters else "vout"
    graph = (
        "[0:v]split=2[base][tocrop];"
        f"[tocrop]crop=w={w}:h={h}:x={x}:y={y},gblur=sigma={max(1, strength)}[blurred];"
        f"[base][blurred]overlay=x={x}:y={y}[{final_label}]"
    )
    if extra_filters:
        graph += f";[merged]{extra_filters}[vout]"
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
    notify("Marca d'água borrada.")
    logger.info(
        "Marca d'água borrada (%s, área %dx%d @ %d,%d, sigma=%d): %s",
        "GPU" if gpu_args else "CPU", w, h, x, y, strength, output_path,
    )
    return output_path


def cover_watermark(
    source: str | Path,
    output_path: str | Path,
    region: WatermarkRegion,
    cover_image: str | Path,
    use_gpu: bool = True,
    crf: int = 20,
    frame_size: tuple[int, int] | None = None,
    on_progress: Callable[[str], None] | None = None,
    extra_filters: str | None = None,
) -> Path:
    """Cola `cover_image` (esticada pra caber exatamente na área marcada)
    por cima da marca d'água, quadro a quadro.

    `cover_image` pode ter transparência (PNG com alpha): as partes
    transparentes deixam o vídeo original aparecer por baixo — útil pra
    colar só um logo/texto sem uma caixa sólida ao redor. Combine com
    `remove_watermark` antes se a marca original precisar sumir de vez (a
    cobertura sozinha só esconde o que ela realmente cobre; se sobrar
    transparência em cima da marca antiga, ela continua visível ali).

    `extra_filters` (opcional): ver `remove_watermark`.
    """
    source = Path(source)
    output_path = Path(output_path)
    cover_image = Path(cover_image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cover_image.exists():
        raise AutoShortsError(f"Imagem de cobertura não encontrada: {cover_image}")

    def notify(message: str) -> None:
        logger.info(message)
        if on_progress:
            on_progress(message)

    frame_w, frame_h = resolve_frame_size(source, frame_size)
    rect = region.clamp(frame_w, frame_h)

    notify("Cobrindo marca d'água...")
    gpu_args = use_gpu and ffmpeg_utils.gpu_encoder_args(crf)
    encoder_args = gpu_args or ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
    final_label = "merged" if extra_filters else "vout"
    graph = (
        f"[1:v]format=rgba,scale={rect.w}:{rect.h}[cover];"
        f"[0:v][cover]overlay=x={rect.x}:y={rect.y}[{final_label}]"
    )
    if extra_filters:
        graph += f";[merged]{extra_filters}[vout]"
    ffmpeg_utils.run_ffmpeg([
        "-i", str(source), "-i", str(cover_image),
        "-filter_complex", graph,
        "-map", "[vout]", "-map", "0:a?",
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ], timeout=7200)
    notify("Marca d'água coberta.")
    logger.info(
        "Marca d'água coberta (%s, área %dx%d @ %d,%d): %s",
        "GPU" if gpu_args else "CPU", rect.w, rect.h, rect.x, rect.y, output_path,
    )
    return output_path


def remove_and_cover_watermark(
    source: str | Path,
    output_path: str | Path,
    region: WatermarkRegion,
    cover_image: str | Path,
    use_gpu: bool = True,
    crf: int = 20,
    frame_size: tuple[int, int] | None = None,
    on_progress: Callable[[str], None] | None = None,
    extra_filters: str | None = None,
) -> Path:
    """Apaga a marca original (`delogo`) e cola `cover_image` por cima do
    resultado, numa única passada — o combo certo quando `cover_image` tem
    fundo transparente (só assim a marca antiga some por completo em vez de
    continuar visível ao redor das letras novas).

    `extra_filters` (opcional): ver `remove_watermark`.
    """
    source = Path(source)
    output_path = Path(output_path)
    cover_image = Path(cover_image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cover_image.exists():
        raise AutoShortsError(f"Imagem de cobertura não encontrada: {cover_image}")

    def notify(message: str) -> None:
        logger.info(message)
        if on_progress:
            on_progress(message)

    frame_w, frame_h = resolve_frame_size(source, frame_size)
    rect = region.clamp(frame_w, frame_h)

    notify("Removendo e cobrindo marca d'água...")
    gpu_args = use_gpu and ffmpeg_utils.gpu_encoder_args(crf)
    encoder_args = gpu_args or ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
    final_label = "merged" if extra_filters else "vout"
    graph = (
        f"[0:v]delogo=x={rect.x}:y={rect.y}:w={rect.w}:h={rect.h}:show=0[cleaned];"
        f"[1:v]format=rgba,scale={rect.w}:{rect.h}[cover];"
        f"[cleaned][cover]overlay=x={rect.x}:y={rect.y}[{final_label}]"
    )
    if extra_filters:
        graph += f";[merged]{extra_filters}[vout]"
    ffmpeg_utils.run_ffmpeg([
        "-i", str(source), "-i", str(cover_image),
        "-filter_complex", graph,
        "-map", "[vout]", "-map", "0:a?",
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ], timeout=7200)
    notify("Marca d'água removida e coberta.")
    logger.info(
        "Marca d'água removida e coberta (%s, área %dx%d @ %d,%d): %s",
        "GPU" if gpu_args else "CPU", rect.w, rect.h, rect.x, rect.y, output_path,
    )
    return output_path
