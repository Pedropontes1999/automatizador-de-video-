"""Monta a trilha de narração por IA sincronizada por trecho com o tempo
original de cada fala, e troca a trilha de áudio do vídeo (Redublagem).
"""
from __future__ import annotations

import re
from pathlib import Path

from src.audio.tts import audio_duration, synthesize
from src.core.exceptions import AutoShortsError
from src.models.domain import TranscriptSegment
from src.utils.ffmpeg_utils import gpu_encoder_args, run_ffmpeg
from src.utils.logger import get_logger
from src.video.intro_builder import concat_same_encoding

logger = get_logger("redub_builder")

# Limite de ajuste de velocidade (atempo) por trecho: fora desse range a voz
# soaria robótica/esganiçada demais, então prefere-se aceitar um pequeno
# desvio de tempo (compensado no próximo trecho, ver build_narration_track).
_MIN_TEMPO = 0.8
_MAX_TEMPO = 1.3

# Reticências/pontuação repetida ("....", "…", "!!!") viram pausa real na
# fala pro TTS. Texto traduzido fora do pipeline (colado de um ChatGPT/Claude
# qualquer, sem instrução de tom de narração) costuma vir cheio disso, dando
# o efeito de narração "espaçada" que o tempo de sincronia por trecho não
# previa — normaliza antes de sintetizar, independente de onde o texto veio.
_ELLIPSIS_RE = re.compile(r"\.{2,}|…")
_REPEATED_PUNCT_RE = re.compile(r"([!?,;:])\1+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,!?;:])")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")


def _clean_narration_text(text: str) -> str:
    """Normaliza pontuação repetida antes da síntese (ver comentário acima
    das constantes `_ELLIPSIS_RE`/`_REPEATED_PUNCT_RE`)."""
    cleaned = _ELLIPSIS_RE.sub(",", text)
    cleaned = _REPEATED_PUNCT_RE.sub(r"\1", cleaned)
    cleaned = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    return cleaned.strip(" ,")


def _silence_clip(duration: float, output: Path) -> Path:
    run_ffmpeg([
        "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
        "-ar", "48000", "-ac", "2", str(output),
    ])
    return output


def _segment_clip(
    text: str, voice: str, target_duration: float, workdir: Path, tag: str,
    api_key: str = "", reference_audio: str = "", use_gpu: bool = True,
) -> tuple[Path, float] | None:
    """Sintetiza a fala do trecho e ajusta a velocidade pra caber (aprox.)
    no tempo original. Retorna (caminho, duração real após o ajuste)."""
    raw = synthesize(
        text, voice, workdir / f"{tag}_raw.mp3", api_key=api_key,
        reference_audio=reference_audio, use_gpu=use_gpu,
    )
    if raw is None:
        return None
    raw_duration = audio_duration(raw)
    if raw_duration <= 0:
        return None
    factor = raw_duration / max(target_duration, 0.05)
    factor = min(max(factor, _MIN_TEMPO), _MAX_TEMPO)
    output = workdir / f"{tag}.wav"
    run_ffmpeg([
        "-i", str(raw), "-filter:a", f"atempo={factor:.3f}",
        "-ar", "48000", "-ac", "2", str(output),
    ])
    return output, raw_duration / factor


def build_narration_track(
    segments: list[TranscriptSegment], voice: str, workdir: Path, api_key: str = "",
    reference_audio: str = "", use_gpu: bool = True,
) -> Path:
    """Gera uma trilha de narração de IA contínua, sincronizada por trecho.

    Sempre que possível, cada trecho novo é realinhado ao `start` original
    (insere silêncio se a narração de IA está adiantada); se um trecho
    anterior estourou o tempo mesmo com o `atempo` limitado, o próximo
    começa colado, sem esperar — evita que o desvio se acumule ao longo do
    vídeo inteiro em vez de corrigir só no ponto onde ele aconteceu.

    O silêncio inserido antes de cada trecho nunca passa da pausa que já
    existia ali no vídeo original (`seg.start` menos o fim do trecho
    anterior): sem esse teto, um trecho traduzido que sai mais curto que o
    original (comum na Redublagem — a tradução muda a duração da fala, mas
    o tempo-alvo de cada trecho continua sendo o do idioma original) atrasa
    o cursor, e a pausa antes do próximo trecho vira maior que a do vídeo
    original, dando a sensação de narração "pausada/espaçada".
    """
    pieces: list[Path] = []
    cursor = 0.0
    prev_end = 0.0
    for i, seg in enumerate(segments):
        text = _clean_narration_text(seg.text.strip())
        if not text:
            continue
        original_gap = max(seg.start - prev_end, 0.0)
        gap = min(seg.start - cursor, original_gap)
        if gap > 0.02:
            pieces.append(_silence_clip(gap, workdir / f"gap_{i:04d}.wav"))
            cursor += gap
        result = _segment_clip(
            text, voice, seg.duration, workdir, f"seg_{i:04d}",
            api_key=api_key, reference_audio=reference_audio, use_gpu=use_gpu,
        )
        prev_end = seg.end
        if result is None:
            logger.warning("Narração do trecho %d falhou; seguindo sem ele.", i)
            continue
        clip, actual_duration = result
        pieces.append(clip)
        cursor += actual_duration
    if not pieces:
        raise AutoShortsError("Nenhum trecho de narração foi gerado.")
    return concat_same_encoding(pieces, workdir / "narracao_completa.wav", workdir)


def _escape_path(path: str | Path) -> str:
    """Escapa um caminho Windows para dentro de filtros FFmpeg."""
    return str(path).replace("\\", "\\\\").replace(":", "\\:")


def mux_final_audio(
    video_path: str | Path,
    narration_track: str | Path,
    music_path: str | Path | None,
    output: str | Path,
    duration: float,
    music_volume: int = 20,
    use_gpu: bool = True,
    crf: int = 20,
) -> Path:
    """Troca a trilha de áudio do vídeo original pela narração de IA + uma
    música de fundo em loop escolhida pelo usuário.

    O áudio original do vídeo (voz antiga + música/efeitos) é sempre
    descartado por completo — não só a voz. Se `music_path` for informado,
    ela toca em loop do início ao fim do vídeo (repete se for mais curta,
    corta se for mais longa); sem música, sobra só a narração nova.

    O vídeo é sempre reencodado para H.264 (GPU quando disponível, senão
    CPU) em vez de copiado (`-c:v copy`): o vídeo de origem pode vir em
    AV1/VP9 (comum em downloads do YouTube), formatos que muitos players e
    editores não reproduzem — H.264 é o mais compatível.
    """
    output = Path(output)
    inputs = ["-i", str(video_path), "-i", str(narration_track)]
    if music_path is not None:
        vol = max(0.0, min(music_volume / 100.0, 1.5))
        # loop=0 repete a música indefinidamente; amix com duration=first
        # (a narração, já com duração fixa abaixo) corta a música bem no
        # fim do vídeo, sem precisar saber a duração dela de antemão.
        audio_graph = (
            f"[1:a]apad,atrim=0:{duration:.3f},asetpts=N/SR/TB[narr];"
            f"amovie='{_escape_path(music_path)}':loop=0,"
            f"asetpts=N/SR/TB,aresample=48000,volume={vol:.2f}[bgm];"
            f"[narr][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
    else:
        audio_graph = f"[1:a]apad,atrim=0:{duration:.3f},asetpts=N/SR/TB[aout]"
    gpu_args = use_gpu and gpu_encoder_args(crf)
    video_args = gpu_args or ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
    # Sem GPU, o encode de vídeo (libx264) é CPU-bound e escala com a
    # duração — um timeout fixo (ex.: 1h) corta no meio vídeos longos que
    # simplesmente precisam de mais tempo, mesmo progredindo normalmente.
    # Usa um múltiplo generoso da duração do vídeo em vez de um valor fixo,
    # mantendo um piso pra vídeos curtos não ficarem reféns de travamentos
    # reais do ffmpeg.
    timeout = max(3600, int(duration * 4) + 600)
    run_ffmpeg([
        *inputs,
        "-filter_complex", audio_graph,
        "-map", "0:v", "-map", "[aout]",
        *video_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output),
    ], timeout=timeout)
    logger.info(
        "Vídeo redublado exportado (%s): %s", "GPU" if gpu_args else "CPU", output,
    )
    return output
