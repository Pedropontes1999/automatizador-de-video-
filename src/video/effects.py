"""Efeitos visuais aplicados aos cortes (filtros FFmpeg, todos gratuitos).

Cada função retorna um trecho de cadeia de filtros que o exportador concatena.
Efeitos disponíveis: fade, auto zoom (lento), jump zoom (pulsos), glow e
motion blur suave.
"""
from __future__ import annotations

from src.utils.logger import get_logger

logger = get_logger("effects")


def fade_filter(duration: float, fade_time: float = 0.35) -> str:
    """Fade in no início e fade out no fim do corte."""
    out_start = max(duration - fade_time, 0.0)
    return f"fade=t=in:st=0:d={fade_time},fade=t=out:st={out_start:.2f}:d={fade_time}"


def auto_zoom_filter(width: int, height: int, fps: int, duration: float) -> str:
    """Zoom lento contínuo (1.00 -> 1.06) ao longo do corte, via zoompan."""
    total_frames = max(int(duration * fps), 1)
    return (
        f"zoompan=z='1+0.06*on/{total_frames}'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:fps={fps}:s={width}x{height}"
    )


def jump_zoom_filter(width: int, height: int, fps: int, interval: float = 5.0) -> str:
    """Jump zoom: punch-in de 8% a cada `interval` segundos por ~0.8s."""
    return (
        f"zoompan=z='if(lt(mod(on/{fps}\\,{interval})\\,0.8)\\,1.08\\,1.0)'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:fps={fps}:s={width}x{height}"
    )


def glow_filter(opacity: float = 0.18) -> str:
    """Brilho suave: mistura o frame com sua versão desfocada (modo screen)."""
    return (
        f"split[glow_a][glow_b];"
        f"[glow_b]gblur=sigma=18[glow_blur];"
        f"[glow_a][glow_blur]blend=all_mode=screen:all_opacity={opacity}"
    )


def motion_blur_filter() -> str:
    """Motion blur leve misturando frames consecutivos."""
    return "tmix=frames=2:weights='0.7 0.3'"


def build_effects_chain(
    effects: dict[str, bool],
    width: int,
    height: int,
    fps: int,
    duration: float,
) -> list[str]:
    """Monta a lista de filtros de efeitos conforme as configurações.

    Nota: auto_zoom e jump_zoom são mutuamente exclusivos (o jump_zoom vence
    se ambos estiverem ativos, por ser mais marcante em Shorts).
    """
    chain: list[str] = []
    if effects.get("jump_zoom") or effects.get("auto_zoom"):
        # zoompan gera frames por contagem própria (`on`/fps); se o vídeo de
        # origem não estiver em taxa de quadros perfeitamente constante, isso
        # dessincroniza vídeo e áudio ao longo do corte. Forçar CFR aqui,
        # logo antes do zoompan, elimina o desvio.
        chain.append(f"fps={fps}")
    if effects.get("jump_zoom"):
        chain.append(jump_zoom_filter(width, height, fps))
    elif effects.get("auto_zoom"):
        chain.append(auto_zoom_filter(width, height, fps, duration))
    if effects.get("glow"):
        chain.append(glow_filter())
    if effects.get("motion_blur"):
        chain.append(motion_blur_filter())
    if effects.get("fade", True):
        chain.append(fade_filter(duration))
    logger.debug("Efeitos ativos: %d filtros", len(chain))
    return chain
