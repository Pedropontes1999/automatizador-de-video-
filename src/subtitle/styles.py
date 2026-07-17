"""Estilos visuais de legendas (temas prontos).

Cada estilo define fonte, tamanho, cores (normal e palavra ativa), contorno,
posição e animação. Cores em formato ASS: &HAABBGGRR (alfa-azul-verde-vermelho).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubtitleStyle:
    """Definição completa de um tema de legenda."""

    name: str
    font: str
    font_size: int              # em pixels para vídeo 1080x1920
    primary_color: str          # cor do texto normal (ASS &HAABBGGRR)
    highlight_color: str        # cor da palavra ativa
    outline_color: str
    outline_width: float
    shadow: float
    bold: bool
    uppercase: bool
    margin_v: int               # distância da borda inferior (px)
    words_per_line: int         # palavras exibidas por bloco
    pop_animation: bool         # palavra ativa "pula" (escala 100->118%)


# Catálogo de temas (cores ASS: lembre-se, ordem é Azul-Verde-Vermelho!).
STYLES: dict[str, SubtitleStyle] = {
    "TikTok": SubtitleStyle(
        name="TikTok", font="Arial Black", font_size=88,
        primary_color="&H00FFFFFF",       # branco
        highlight_color="&H0000D7FF",     # amarelo-ouro
        outline_color="&H00000000", outline_width=5.0, shadow=1.0,
        bold=True, uppercase=True, margin_v=520, words_per_line=3,
        pop_animation=True,
    ),
    "Hormozi": SubtitleStyle(
        name="Hormozi", font="Arial Black", font_size=92,
        primary_color="&H00FFFFFF",
        highlight_color="&H0000FF00",     # verde-limão
        outline_color="&H00000000", outline_width=6.0, shadow=2.0,
        bold=True, uppercase=True, margin_v=560, words_per_line=2,
        pop_animation=True,
    ),
    "MrBeast": SubtitleStyle(
        name="MrBeast", font="Arial Black", font_size=96,
        primary_color="&H0000FFFF",       # amarelo
        highlight_color="&H000000FF",     # vermelho
        outline_color="&H00000000", outline_width=6.0, shadow=2.5,
        bold=True, uppercase=True, margin_v=540, words_per_line=3,
        pop_animation=True,
    ),
    "Minimalista": SubtitleStyle(
        name="Minimalista", font="Arial", font_size=64,
        primary_color="&H00FFFFFF",
        highlight_color="&H00FFFFFF",
        outline_color="&H64000000", outline_width=2.0, shadow=0.0,
        bold=False, uppercase=False, margin_v=440, words_per_line=5,
        pop_animation=False,
    ),
    "Podcast": SubtitleStyle(
        name="Podcast", font="Georgia", font_size=68,
        primary_color="&H00F5F5F5",
        highlight_color="&H00D7A55A",     # azul-acinzentado quente
        outline_color="&H96000000", outline_width=3.0, shadow=1.0,
        bold=False, uppercase=False, margin_v=460, words_per_line=4,
        pop_animation=False,
    ),
    "Gaming": SubtitleStyle(
        name="Gaming", font="Impact", font_size=84,
        primary_color="&H00FFFFFF",
        highlight_color="&H00FF00B4",     # roxo neon
        outline_color="&H00320096", outline_width=5.0, shadow=2.0,
        bold=True, uppercase=True, margin_v=520, words_per_line=3,
        pop_animation=True,
    ),
    "Cinema": SubtitleStyle(
        name="Cinema", font="Times New Roman", font_size=60,
        primary_color="&H00E8E8E8",
        highlight_color="&H00E8E8E8",
        outline_color="&HC8000000", outline_width=1.5, shadow=0.0,
        bold=False, uppercase=False, margin_v=380, words_per_line=6,
        pop_animation=False,
    ),
}


def get_style(name: str) -> SubtitleStyle:
    """Retorna o estilo pelo nome (TikTok como fallback seguro)."""
    return STYLES.get(name, STYLES["TikTok"])
