"""Geração de legendas ASS estilo TikTok com palavras sincronizadas.

Como funciona a animação palavra-a-palavra:
- As palavras são agrupadas em blocos curtos (2-6 palavras por estilo).
- Para cada palavra ativa é emitida uma linha `Dialogue` cobrindo somente a
  duração daquela palavra, com o bloco inteiro renderizado e a palavra ativa
  destacada (cor diferente + animação de "pop" com \\t e \\fscx/\\fscy).
- O resultado é queimado no vídeo pelo filtro `ass` do FFmpeg.

Suporta remapeamento de tempo: quando silêncios são removidos do corte, os
timestamps das palavras são convertidos para a linha do tempo editada.
"""
from __future__ import annotations

from pathlib import Path

from src.models.domain import TranscriptWord
from src.subtitle.styles import SubtitleStyle
from src.utils.logger import get_logger

logger = get_logger("subtitles")


class TimeRemapper:
    """Converte tempo original do corte -> tempo da linha editada.

    `keep_intervals` são os trechos mantidos (saída de `keep_intervals()` do
    módulo de silêncio), em tempo local do corte.
    """

    def __init__(self, keep_intervals: list[tuple[float, float]] | None) -> None:
        self._intervals = keep_intervals or []
        # Tempo acumulado no início de cada intervalo mantido.
        self._offsets: list[float] = []
        acc = 0.0
        for start, end in self._intervals:
            self._offsets.append(acc)
            acc += end - start

    def remap(self, t: float) -> float | None:
        """Mapeia o tempo `t`; retorna None se `t` caiu em trecho removido."""
        if not self._intervals:
            return t
        for (start, end), offset in zip(self._intervals, self._offsets):
            if start <= t <= end:
                return offset + (t - start)
            if t < start:
                # Caiu em uma janela removida: gruda no início do próximo trecho.
                return offset
        return None


def _fmt_time(seconds: float) -> str:
    """Formata segundos no padrão ASS h:mm:ss.cs."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_header(style: SubtitleStyle, width: int, height: int) -> str:
    """Cabeçalho ASS com o estilo base.

    Os tamanhos dos estilos são calibrados para 1080x1920 (vertical); aqui
    tudo é escalado proporcionalmente à altura real do vídeo — assim as
    legendas ficam com o tamanho certo também no formato original/16:9.
    """
    bold = -1 if style.bold else 0
    factor = height / 1920.0
    font_size = max(int(style.font_size * factor), 18)
    margin_v = max(int(style.margin_v * factor), 30)
    outline = round(style.outline_width * factor, 1)
    shadow = round(style.shadow * factor, 1)
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\n"
        "WrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Main,{style.font},{font_size},{style.primary_color},"
        f"{style.primary_color},{style.outline_color},&H96000000,{bold},0,0,0,"
        f"100,100,0,0,1,{outline},{shadow},2,60,60,"
        f"{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Text\n"
    )


def _group_words(
    words: list[TranscriptWord], per_line: int,
) -> list[list[TranscriptWord]]:
    """Agrupa palavras em blocos, quebrando também em pausas > 0.8s."""
    groups: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    for word in words:
        if current and (
            len(current) >= per_line or word.start - current[-1].end > 0.8
        ):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def _render_block(
    block: list[TranscriptWord], active_index: int, style: SubtitleStyle,
) -> str:
    """Renderiza o texto do bloco com a palavra ativa destacada e animada."""
    parts: list[str] = []
    for i, word in enumerate(block):
        text = word.text.upper() if style.uppercase else word.text
        text = text.replace("{", "").replace("}", "")  # sanitiza tags ASS
        if i == active_index:
            tags = f"\\c{style.highlight_color}"
            if style.pop_animation:
                # Pop: escala 100 -> 118 -> 108 nos primeiros 120 ms.
                tags += (
                    "\\fscx100\\fscy100"
                    "\\t(0,60,\\fscx118\\fscy118)"
                    "\\t(60,120,\\fscx108\\fscy108)"
                )
            parts.append(f"{{{tags}}}{text}{{\\r}}")
        else:
            parts.append(text)
    return " ".join(parts)


def generate_ass(
    words: list[TranscriptWord],
    style: SubtitleStyle,
    output_path: str | Path,
    cut_start: float,
    remapper: TimeRemapper | None = None,
    width: int = 1080,
    height: int = 1920,
) -> Path | None:
    """Gera o arquivo .ass do corte.

    Args:
        words: palavras do trecho (timestamps do vídeo ORIGINAL).
        style: tema visual escolhido.
        output_path: destino do .ass.
        cut_start: início do corte no vídeo original (converte para tempo local).
        remapper: remapeia tempos quando silêncios foram removidos.
        width/height: resolução do vídeo final.

    Returns:
        Caminho do .ass, ou None se não houver palavras.
    """
    if not words:
        logger.warning("Corte sem palavras — legenda não gerada.")
        return None

    # Converte para tempo local do corte e aplica o remapeamento de edição.
    local_words: list[TranscriptWord] = []
    for w in words:
        # Limpa pontuação "órfã" que o Whisper cola no início das palavras
        # (ex.: ",cara" -> "cara"); palavras vazias são puladas.
        clean_text = w.text.strip().lstrip(",.;:!?…-–—")
        if not clean_text:
            continue
        w = TranscriptWord(text=clean_text, start=w.start, end=w.end)
        start, end = w.start - cut_start, w.end - cut_start
        if remapper is not None:
            mapped_start = remapper.remap(start)
            mapped_end = remapper.remap(end)
            if mapped_start is None or mapped_end is None or mapped_end <= mapped_start:
                continue  # palavra caiu inteira em trecho removido
            start, end = mapped_start, mapped_end
        if end > start >= 0:
            local_words.append(TranscriptWord(text=w.text, start=start, end=end))

    if not local_words:
        return None

    lines: list[str] = [_ass_header(style, width, height)]
    for block in _group_words(local_words, style.words_per_line):
        for i, word in enumerate(block):
            # A linha da palavra ativa termina onde começa a próxima palavra,
            # evitando "buracos" sem legenda dentro do bloco.
            end_time = block[i + 1].start if i + 1 < len(block) else block[i].end
            text = _render_block(block, i, style)
            lines.append(
                f"Dialogue: 0,{_fmt_time(word.start)},{_fmt_time(end_time)},"
                f"Main,,0,0,0,,{text}\n"
            )

    output_path = Path(output_path)
    output_path.write_text("".join(lines), encoding="utf-8-sig")
    logger.info("Legenda gerada: %s (%d palavras)", output_path.name, len(local_words))
    return output_path
