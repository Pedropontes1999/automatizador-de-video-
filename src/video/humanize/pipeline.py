"""Orquestra o Modo Humanizado: sorteia os parâmetros da renderização,
roda o rastreamento de rosto (quando o reenquadramento inteligente está
ligado) e monta a cadeia de filtros de vídeo final.

Só expõe uma função pública (`build_humanize_video_filter`) — quem chama
(o worker da aba Editar Shorts) não precisa saber como cada sub-efeito
funciona por dentro, só encaixar a string resultante no `-filter_complex`
existente.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.video.face_tracker import FaceTracker, FramingResult
from src.video.humanize import color, grain, mirror, sharpen, speed, vignette, zoom_pan
from src.video.humanize.params import HumanizeParams, HumanizeToggles, randomize_params
from src.utils.logger import get_logger

logger = get_logger("humanize")

ProgressFn = Callable[[str], None]


def build_humanize_filter(
    width: int,
    height: int,
    fps: int,
    duration: float,
    toggles: HumanizeToggles,
    params: HumanizeParams,
    framing: FramingResult | None,
) -> str:
    """Monta a cadeia de filtros de vídeo (sem rótulos `[in]`/`[out]`) na
    ordem: zoom/pan (já com reenquadramento embutido) -> espelhamento
    parcial -> cor -> nitidez -> vinheta -> granulado -> velocidade (por
    último, depois de tudo já desenhado no frame)."""
    parts: list[str] = []

    if toggles.zoom or toggles.pan:
        # CFR antes do zoompan: sem isso, um vídeo de origem com frame rate
        # variável dessincroniza áudio/vídeo ao longo do clipe (mesmo motivo
        # documentado em `src/video/effects.py::build_effects_chain`).
        parts.append(f"fps={fps}")
        use_framing = framing if (toggles.smart_reframe and framing) else None
        parts.append(zoom_pan.build_zoom_pan_filter(
            width, height, fps, duration,
            params.zoom_keyframe_times or [0.0, max(duration, 0.001)],
            params.zoom_keyframe_levels or [1.0, 1.0],
            pan_direction=params.pan_direction if toggles.pan else "none",
            framing=use_framing,
        ))

    if toggles.mirror and params.mirror_scene is not None:
        mirror_expr = mirror.mirror_filter(params.mirror_scene)
        if mirror_expr:
            parts.append(mirror_expr)

    if toggles.color and params.color_preset != "none":
        color_expr = color.color_filter(params.color_preset)
        if color_expr:
            parts.append(color_expr)

    sharpen_amount = params.sharpen_amount if toggles.sharpen else 0.0
    if toggles.color and params.color_preset in color.PRESET_SHARPEN_BONUS:
        sharpen_amount += color.PRESET_SHARPEN_BONUS[params.color_preset]
    if sharpen_amount > 0:
        parts.append(sharpen.sharpen_filter(sharpen_amount))

    if toggles.vignette and params.vignette_strength > 0:
        parts.append(vignette.vignette_filter(params.vignette_strength))

    if toggles.grain and params.grain_amount > 0:
        parts.append(grain.grain_filter(params.grain_amount))

    if toggles.speed and abs(params.speed_factor - 1.0) > 1e-6:
        parts.append(speed.speed_filter(params.speed_factor))

    return ",".join(parts)


def build_humanize_video_filter(
    source: str | Path,
    toggles: HumanizeToggles,
    width: int,
    height: int,
    fps: int,
    duration: float,
    on_progress: ProgressFn | None = None,
) -> str:
    """Sorteia os parâmetros dessa renderização e devolve a cadeia de
    filtros pronta pra encaixar num `-filter_complex` existente (string
    vazia se nenhum sub-efeito estiver ativo).

    Roda o rastreamento de rosto (OpenCV) quando o reenquadramento
    inteligente está ligado — pode levar alguns segundos; por isso deve
    sempre ser chamado numa thread de fundo, nunca na GUI.
    """
    def notify(message: str) -> None:
        logger.info(message)
        if on_progress:
            on_progress(message)

    if not toggles.any_active():
        return ""

    params = randomize_params(toggles, duration)
    framing: FramingResult | None = None
    if toggles.smart_reframe and (toggles.zoom or toggles.pan):
        notify("Modo Humanizado: detectando o personagem principal...")
        framing = FaceTracker().track(source, 0.0, duration)

    logger.info(
        "Modo Humanizado sorteado — zoom_max=%.3f pan=%s cor=%s espelho=%s "
        "velocidade=%.4f nitidez=%.3f vinheta=%.3f grão=%.2f%% rosto=%s",
        params.zoom_max, params.pan_direction, params.color_preset,
        params.mirror_scene, params.speed_factor, params.sharpen_amount,
        params.vignette_strength, params.grain_amount,
        "detectado" if (framing and framing.face_found) else "não detectado/desligado",
    )
    notify("Aplicando Modo Humanizado (zoom, pan, cor e variações sutis)...")
    return build_humanize_filter(width, height, fps, duration, toggles, params, framing)
