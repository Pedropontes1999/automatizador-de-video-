"""Zoom dinâmico + movimento de câmera (pontos 1, 2 e 3 do Modo Humanizado):
uma única expressão `zoompan` com keyframes suavizados por easing
(smoothstep = ease-in-out), nunca troca brusca de zoom ou posição.

Reenquadramento inteligente (ponto 3): quando um `FramingResult` com rosto
detectado é passado, o eixo X do pan segue a trajetória do personagem (já
suavizada pelo `FaceTracker`) em vez da varredura direcional sorteada. O
eixo Y só recebe um leve viés pra cima — o tracker atual só segue X (ver
`src/video/face_tracker.py`); estender pra Y ficaria pra uma iteração
futura caso o viés fixo não seja suficiente.

As expressões usam `on/fps` como referência de tempo (frames de saída já
contados em CFR), não a variável `t` do zoompan — mesma convenção já usada
em `src/video/effects.py` (`jump_zoom_filter`), que evita imprecisões de
`t` observadas em vídeos de origem com frame rate variável.
"""
from __future__ import annotations

from src.video.face_tracker import FramingResult

# (sinal_x, sinal_y) de cada direção de pan: a varredura vai de
# -amplitude*sinal até +amplitude*sinal ao longo do vídeo inteiro.
_PAN_AXES: dict[str, tuple[int, int]] = {
    "left_right": (1, 0),
    "right_left": (-1, 0),
    "top_bottom": (0, 1),
    "bottom_top": (0, -1),
    "diagonal_tl_br": (1, 1),
    "diagonal_tr_bl": (-1, 1),
}

_DEFAULT_PAN_AMPLITUDE = 0.35  # fração do espaço de manobra disponível no zoom


def _ease_segment(time_expr: str, t0: float, t1: float, v0: float, v1: float) -> str:
    """Interpolação suave (smoothstep) entre dois keyframes — nunca linear."""
    span = max(t1 - t0, 0.001)
    p = f"clip(({time_expr}-{t0:.3f})/{span:.3f}\\,0\\,1)"
    ease = f"(pow({p}\\,2)*(3-2*{p}))"
    return f"({v0:.4f}+({v1:.4f}-{v0:.4f})*{ease})"


def _piecewise(time_expr: str, times: list[float], values: list[float]) -> str:
    """Expressão aninhada `if(lt(time,t1), segmento, ...)` cobrindo todos os
    intervalos entre keyframes, do último pro primeiro."""
    if len(times) == 1:
        return f"{values[0]:.4f}"
    expr = f"{values[-1]:.4f}"
    pairs = list(zip(times, values))
    for (t0, v0), (t1, v1) in reversed(list(zip(pairs, pairs[1:]))):
        segment = _ease_segment(time_expr, t0, t1, v0, v1)
        expr = f"if(lt({time_expr}\\,{t1:.3f})\\,{segment}\\,{expr})"
    return expr


def build_zoom_pan_filter(
    width: int,
    height: int,
    fps: int,
    duration: float,
    zoom_times: list[float],
    zoom_levels: list[float],
    pan_direction: str = "none",
    pan_amplitude: float = _DEFAULT_PAN_AMPLITUDE,
    framing: FramingResult | None = None,
) -> str:
    """Monta o `zoompan` combinando zoom dinâmico + pan (com ou sem
    reenquadramento inteligente guiado por rosto)."""
    time_expr = f"(on/{fps})"
    zoom_expr = _piecewise(time_expr, zoom_times, zoom_levels)
    sweep = _ease_segment(time_expr, 0.0, max(duration, 0.001), 0.0, 1.0)

    if framing is not None and framing.face_found and framing.centers:
        center_expr = _piecewise(
            time_expr, [t for t, _ in framing.centers], [c for _, c in framing.centers],
        )
        x_offset = f"(({center_expr})-0.5)*(iw-iw/zoom)"
        y_offset = "(-0.06*(ih-ih/zoom))"  # leve viés pra cima (rosto costuma ficar ali)
    else:
        sx, sy = _PAN_AXES.get(pan_direction, (0, 0))
        x_offset = (
            f"({sx}*{pan_amplitude}*(({sweep})-0.5)*(iw-iw/zoom))" if sx else "0"
        )
        y_offset = (
            f"({sy}*{pan_amplitude}*(({sweep})-0.5)*(ih-ih/zoom))" if sy else "0"
        )

    x_expr = f"clip((iw/2-(iw/zoom/2))+{x_offset}\\,0\\,iw-iw/zoom)"
    y_expr = f"clip((ih/2-(ih/zoom/2))+{y_offset}\\,0\\,ih-ih/zoom)"

    return (
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}'"
        f":d=1:fps={fps}:s={width}x{height}"
    )
