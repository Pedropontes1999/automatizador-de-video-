"""Reenquadramento automático 9:16 (formato Shorts).

Duas estratégias:
1. **Crop dinâmico com câmera virtual** — quando há rosto/pessoa detectada,
   a janela 9:16 segue o centro de interesse calculado pelo `FaceTracker`,
   com movimento suave (expressão por keyframes avaliada pelo FFmpeg).
2. **Fundo desfocado** — quando não há rosto detectável (ou vídeo já é
   vertical), o vídeo inteiro é encaixado sobre uma versão ampliada e
   desfocada dele mesmo.
"""
from __future__ import annotations

from src.video.face_tracker import FramingResult
from src.utils.logger import get_logger

logger = get_logger("reframer")

MAX_KEYFRAMES = 40  # limite de keyframes na expressão do FFmpeg


def build_reframe_filter(
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    framing: FramingResult,
    cut_start: float,
) -> str:
    """Monta a cadeia de filtros de vídeo para converter o corte em 9:16.

    Args:
        source_width/height: resolução do vídeo original.
        target_width/height: resolução final (ex.: 1080x1920).
        framing: resultado do rastreamento de rosto do trecho.
        cut_start: início do corte no vídeo original (para converter os tempos
            do rastreamento em tempos locais do corte).

    Returns:
        String de filtros (sem `-vf`), ex.: "crop=...,scale=1080:1920".
    """
    is_portrait = source_height >= source_width
    if is_portrait or not framing.face_found:
        return _blur_background_filter(target_width, target_height)
    return _dynamic_crop_filter(
        source_width, source_height, target_width, target_height, framing, cut_start,
    )


# --------------------------------------------------------------------------- #
def _blur_background_filter(tw: int, th: int) -> str:
    """Vídeo original centralizado sobre fundo desfocado ampliado."""
    return (
        f"split[bg][fg];"
        f"[bg]scale={tw}:{th}:force_original_aspect_ratio=increase,"
        f"crop={tw}:{th},gblur=sigma=30,eq=brightness=-0.08[bgout];"
        f"[fg]scale={tw}:-2[fgout];"
        f"[bgout][fgout]overlay=(W-w)/2:(H-h)/2"
    )


def _dynamic_crop_filter(
    sw: int, sh: int, tw: int, th: int, framing: FramingResult, cut_start: float,
) -> str:
    """Crop 9:16 cuja posição X segue o rosto (expressão por keyframes)."""
    # Largura da janela 9:16 dentro do vídeo original.
    crop_w = int(sh * tw / th)
    crop_w -= crop_w % 2  # par, exigido pelo H264
    if crop_w >= sw:      # vídeo mais "estreito" que 9:16 -> fundo desfocado
        return _blur_background_filter(tw, th)

    keyframes = _reduce_keyframes(framing.centers, cut_start)
    x_expr = _piecewise_expression(keyframes, sw, crop_w)
    logger.debug("Crop dinâmico: w=%d, keyframes=%d", crop_w, len(keyframes))
    return f"crop={crop_w}:{sh}:x='{x_expr}':y=0,scale={tw}:{th}"


def _reduce_keyframes(
    centers: list[tuple[float, float]], cut_start: float,
) -> list[tuple[float, float]]:
    """Converte para tempo local do corte e limita a MAX_KEYFRAMES pontos."""
    local = [(max(0.0, t - cut_start), x) for t, x in centers]
    if len(local) <= MAX_KEYFRAMES:
        return local
    step = len(local) / MAX_KEYFRAMES
    return [local[int(i * step)] for i in range(MAX_KEYFRAMES)]


def _piecewise_expression(
    keyframes: list[tuple[float, float]], sw: int, crop_w: int,
) -> str:
    """Gera expressão FFmpeg de interpolação linear entre keyframes.

    A expressão devolve a posição X do crop, limitada a [0, sw - crop_w].
    """
    max_x = sw - crop_w

    def x_of(center_norm: float) -> float:
        return min(max(center_norm * sw - crop_w / 2.0, 0.0), float(max_x))

    if not keyframes:
        return str(max_x // 2)
    if len(keyframes) == 1:
        return f"{x_of(keyframes[0][1]):.1f}"

    # if(lt(t,t1), lerp(x0,x1), if(lt(t,t2), lerp(x1,x2), ... xN))
    expr = f"{x_of(keyframes[-1][1]):.1f}"
    for (t0, c0), (t1, c1) in reversed(list(zip(keyframes, keyframes[1:]))):
        x0, x1 = x_of(c0), x_of(c1)
        span = max(t1 - t0, 0.001)
        segment = f"{x0:.1f}+({x1:.1f}-{x0:.1f})*(t-{t0:.2f})/{span:.2f}"
        expr = f"if(lt(t\\,{t1:.2f})\\,{segment}\\,{expr})"
    return expr
