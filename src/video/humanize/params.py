"""Quais sub-efeitos do Modo Humanizado estão ligados (`HumanizeToggles`,
vem da GUI) e os parâmetros sorteados para UMA renderização específica
(`HumanizeParams`, ponto 10 do pedido: aleatorização — cada exportação deve
sair com uma combinação diferente de valores)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from src.config import constants as C


@dataclass
class HumanizeToggles:
    """Quais sub-efeitos estão ativos (checkboxes do menu avançado)."""

    zoom: bool = True
    pan: bool = True
    smart_reframe: bool = True
    color: bool = True
    sharpen: bool = True
    mirror: bool = False
    vignette: bool = True
    grain: bool = False
    speed: bool = True
    mirror_probability: float = 0.15  # 0..1

    def any_active(self) -> bool:
        """Se nenhum sub-efeito estiver ligado, não vale nem rastrear rosto
        nem montar filtro nenhum."""
        return any((
            self.zoom, self.pan, self.color, self.sharpen,
            self.mirror, self.vignette, self.grain, self.speed,
        ))


@dataclass
class HumanizeParams:
    """Parâmetros sorteados para uma renderização específica."""

    zoom_max: float = 1.0
    zoom_keyframe_times: list[float] = field(default_factory=list)
    zoom_keyframe_levels: list[float] = field(default_factory=list)
    pan_direction: str = "none"
    color_preset: str = "none"
    mirror_scene: tuple[float, float] | None = None
    speed_factor: float = 1.0
    sharpen_amount: float = 0.0
    vignette_strength: float = 0.0
    grain_amount: float = 0.0


def randomize_params(
    toggles: HumanizeToggles, duration: float, rng: random.Random | None = None,
) -> HumanizeParams:
    """Sorteia um conjunto de parâmetros respeitando só os sub-efeitos
    ligados (os desligados ficam com o valor neutro/default do dataclass)."""
    rng = rng or random.Random()
    params = HumanizeParams()

    if toggles.zoom:
        params.zoom_max = round(rng.uniform(C.HUMANIZE_ZOOM_MIN, C.HUMANIZE_ZOOM_MAX), 3)
        params.zoom_keyframe_times, params.zoom_keyframe_levels = _random_zoom_keyframes(
            duration, params.zoom_max, rng,
        )
    if toggles.pan:
        params.pan_direction = rng.choice(C.HUMANIZE_PAN_DIRECTIONS)
    if toggles.color:
        params.color_preset = rng.choice(C.HUMANIZE_COLOR_PRESETS)
    if toggles.mirror and rng.random() < max(0.0, min(toggles.mirror_probability, 1.0)):
        params.mirror_scene = _random_scene(duration, rng)
    if toggles.speed:
        params.speed_factor = round(rng.uniform(C.HUMANIZE_SPEED_MIN, C.HUMANIZE_SPEED_MAX), 4)
    if toggles.sharpen:
        params.sharpen_amount = round(rng.uniform(0.05, 0.20), 3)
    if toggles.vignette:
        params.vignette_strength = round(rng.uniform(0.05, 0.15), 3)
    if toggles.grain:
        params.grain_amount = round(rng.uniform(C.HUMANIZE_GRAIN_MIN, C.HUMANIZE_GRAIN_MAX), 2)
    return params


def _random_zoom_keyframes(
    duration: float, zoom_max: float, rng: random.Random,
) -> tuple[list[float], list[float]]:
    """Pontos de zoom a cada 2-5s (ponto 1 do pedido), com nível aleatório
    entre 101% e o teto sorteado pra essa renderização."""
    times = [0.0]
    t = 0.0
    while t < duration:
        t += rng.uniform(
            C.HUMANIZE_ZOOM_SEGMENT_MIN_SECONDS, C.HUMANIZE_ZOOM_SEGMENT_MAX_SECONDS,
        )
        times.append(min(t, duration))
    if times[-1] < duration:
        times.append(duration)
    low = min(C.HUMANIZE_ZOOM_MIN, zoom_max)
    levels = [round(rng.uniform(low, zoom_max), 3) for _ in times]
    return times, levels


def _random_scene(duration: float, rng: random.Random) -> tuple[float, float]:
    """Janela curta e aleatória do vídeo (nunca o vídeo inteiro)."""
    scene_len = min(duration, rng.uniform(2.0, 6.0))
    start = rng.uniform(0.0, max(duration - scene_len, 0.0))
    return start, start + scene_len
