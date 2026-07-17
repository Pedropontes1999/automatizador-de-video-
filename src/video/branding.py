"""Identidade visual dos Shorts: marca d'água, textos, barra de progresso,
música de fundo e narração por IA.

Tudo é aplicado como uma extensão do -filter_complex já montado pelo
exportador: as saídas [vout]/[aout] são renomeadas para [vbase]/[abase] e as
camadas de estilo são encadeadas por cima, gerando novas [vout]/[aout].
As mídias extras (logo, música, narração) entram via filtros movie/amovie —
sem mexer nos inputs do FFmpeg.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config import constants as C
from src.config.settings import Settings
from src.utils.logger import get_logger

logger = get_logger("branding")

_MARGIN = 40  # px de respiro da marca d'água até a borda
_BAR_HEIGHT = 14
_BAR_COLOR = "0x5865F2"  # roxo do tema


@dataclass
class BrandingSpec:
    """Tudo que o estilo precisa para um corte específico."""

    settings: Settings
    out_width: int
    out_height: int
    duration: float          # duração final (já editada) do corte
    workdir: Path            # pasta temp para os .txt do drawtext
    tag: str = "cut"         # prefixo único por corte (evita colisão de .txt)
    part_text: str = ""      # ex.: "Parte 03" (vazio = não mostra)
    tts_path: Path | None = None
    tts_duration: float = 0.0


def apply_branding(graph: str, spec: BrandingSpec) -> str:
    """Acrescenta as camadas de estilo ao -filter_complex do corte."""
    video_steps = _video_steps(spec)
    audio_steps = _audio_steps(spec)
    if not video_steps and not audio_steps:
        return graph

    if video_steps:
        graph = graph.replace("[vout]", "[vbase]")
        current = "[vbase]"
        for i, (prelude, chain) in enumerate(video_steps):
            label = "[vout]" if i == len(video_steps) - 1 else f"[vb{i}]"
            if prelude:
                graph += f";{prelude}"
            graph += f";{current}{chain}{label}"
            current = label
    if audio_steps:
        graph = graph.replace("[aout]", "[abase]")
        current = "[abase]"
        for i, (prelude, chain) in enumerate(audio_steps):
            label = "[aout]" if i == len(audio_steps) - 1 else f"[ab{i}]"
            if prelude:
                graph += f";{prelude}"
            graph += f";{current}{chain}{label}"
            current = label
    logger.debug(
        "Branding: %d camadas de vídeo, %d de áudio.",
        len(video_steps), len(audio_steps),
    )
    return graph


# --------------------------------------------------------------------------- #
# Vídeo
# --------------------------------------------------------------------------- #
def _video_steps(spec: BrandingSpec) -> list[tuple[str, str]]:
    """Lista de (subgrafo auxiliar, cadeia aplicada ao stream principal)."""
    s = spec.settings
    steps: list[tuple[str, str]] = []

    if s.watermark_path and Path(s.watermark_path).exists():
        wm_width = int(spec.out_width * s.watermark_size / 100)
        wm_width -= wm_width % 2
        alpha = max(0.05, min(s.watermark_opacity / 100.0, 1.0))
        x, y = _corner_expr(s.watermark_position)
        prelude = (
            f"movie='{_escape_path(s.watermark_path)}',"
            f"scale={wm_width}:-1,format=rgba,colorchannelmixer=aa={alpha:.2f}[wm]"
        )
        steps.append((prelude, "[wm]overlay=" + f"{x}:{y}"))
    elif s.watermark_path:
        logger.warning("Marca d'água não encontrada: %s", s.watermark_path)

    # Selo do canal (foto + nome + @), centralizado no topo ou rodapé.
    if (s.channel_name or s.channel_handle) and C.CHANNEL_BADGE_FILE.exists():
        badge_w = int(spec.out_width * 0.55)
        badge_w -= badge_w % 2
        y = "90" if s.channel_badge_position == "top" else "H-h-90"
        prelude = (
            f"movie='{_escape_path(C.CHANNEL_BADGE_FILE)}',"
            f"scale={badge_w}:-1,format=rgba[badge]"
        )
        steps.append((prelude, f"[badge]overlay=(W-w)/2:{y}"))

    font = _find_font()
    if s.hook_text.strip() and font:
        hook = s.hook_text.strip()
        steps.append(("", _drawtext(
            hook, font, size=_fit_fontsize(hook, spec.out_width, 54), y=110,
            textfile=spec.workdir / f"{spec.tag}_hook.txt",
        )))
    if spec.part_text and font:
        y = 190 if s.hook_text.strip() else 110
        steps.append(("", _drawtext(
            spec.part_text, font, size=64, y=y,
            textfile=spec.workdir / f"{spec.tag}_part.txt",
        )))
    if (s.hook_text.strip() or spec.part_text) and not font:
        logger.warning("Nenhuma fonte encontrada em C:/Windows/Fonts; texto pulado.")

    if s.progress_bar and spec.duration > 0:
        prelude = f"color=c={_BAR_COLOR}:s={spec.out_width}x{_BAR_HEIGHT}[pb]"
        chain = (
            f"[pb]overlay=shortest=1"
            f":x='-W+W*t/{spec.duration:.2f}':y=H-{_BAR_HEIGHT}"
        )
        steps.append((prelude, chain))
    return steps


def _drawtext(text: str, font: str, size: int, y: int, textfile: Path) -> str:
    """Texto centralizado no topo com contorno preto (estilo Shorts).

    O texto vai em um arquivo (textfile=) em vez de inline: o filtergraph tem
    dois níveis de escape e qualquer apóstrofo/dois-pontos quebraria o filtro.
    """
    textfile.write_text(text, encoding="utf-8")
    return (
        f"drawtext=fontfile='{_escape_path(font)}':expansion=none"
        f":textfile='{_escape_path(textfile)}'"
        f":fontcolor=white:fontsize={size}:borderw=4:bordercolor=black"
        f":x=(w-text_w)/2:y={y}"
    )


def _fit_fontsize(text: str, video_width: int, max_size: int) -> int:
    """Reduz a fonte para textos longos caberem na largura do vídeo.

    Aproximação: caractere bold ocupa ~0.58x o tamanho da fonte.
    """
    usable = video_width - 2 * _MARGIN
    fitted = int(usable / (0.58 * max(len(text), 1)))
    return max(24, min(max_size, fitted))


def _corner_expr(position: str) -> tuple[str, str]:
    """Expressões x/y do overlay para cada canto."""
    x = f"{_MARGIN}" if "left" in position else f"W-w-{_MARGIN}"
    y = f"{_MARGIN}" if "top" in position else f"H-h-{_MARGIN}"
    return x, y


# --------------------------------------------------------------------------- #
# Áudio
# --------------------------------------------------------------------------- #
def _audio_steps(spec: BrandingSpec) -> list[tuple[str, str]]:
    """Narração (com ducking do áudio original) e música de fundo."""
    s = spec.settings
    steps: list[tuple[str, str]] = []

    if spec.tts_path is not None and spec.tts_duration > 0:
        prelude = f"amovie='{_escape_path(spec.tts_path)}',aresample=48000[tts]"
        # Abaixa o áudio original enquanto a narração fala (ducking simples).
        duck = f"volume=0.25:enable='lt(t,{spec.tts_duration:.2f})'"
        chain = (
            f"{duck}[aduck];[aduck][tts]"
            f"amix=inputs=2:duration=first:dropout_transition=0:normalize=0"
        )
        steps.append((prelude, chain))

    if s.music_path and Path(s.music_path).exists():
        volume = max(0.0, min(s.music_volume / 100.0, 1.0))
        prelude = (
            f"amovie='{_escape_path(s.music_path)}':loop=0,"
            f"asetpts=N/SR/TB,aresample=48000,volume={volume:.2f}[bgm]"
        )
        chain = "[bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0"
        steps.append((prelude, chain))
    elif s.music_path:
        logger.warning("Música de fundo não encontrada: %s", s.music_path)
    return steps


# --------------------------------------------------------------------------- #
def _escape_path(path: str | Path) -> str:
    """Escapa um caminho Windows para dentro de filtros FFmpeg."""
    return str(path).replace("\\", "/").replace(":", "\\:")


def _find_font() -> str | None:
    """Fonte em negrito do Windows para os textos queimados no vídeo."""
    for name in ("arialbd.ttf", "arial.ttf", "impact.ttf", "seguisb.ttf"):
        candidate = Path("C:/Windows/Fonts") / name
        if candidate.exists():
            return str(candidate)
    return None
