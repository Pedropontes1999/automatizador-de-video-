"""Monta a trilha de narração por IA sincronizada por trecho com o tempo
original de cada fala, e troca a trilha de áudio do vídeo (Redublagem).
"""
from __future__ import annotations

from pathlib import Path

from src.audio.tts import audio_duration, synthesize
from src.core.exceptions import AutoShortsError
from src.models.domain import TranscriptSegment
from src.utils.ffmpeg_utils import run_ffmpeg
from src.utils.logger import get_logger
from src.video.intro_builder import concat_same_encoding

logger = get_logger("redub_builder")

# Limite de ajuste de velocidade (atempo) por trecho: fora desse range a voz
# soaria robótica/esganiçada demais, então prefere-se aceitar um pequeno
# desvio de tempo (compensado no próximo trecho, ver build_narration_track).
_MIN_TEMPO = 0.8
_MAX_TEMPO = 1.3


def _silence_clip(duration: float, output: Path) -> Path:
    run_ffmpeg([
        "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
        "-ar", "48000", "-ac", "2", str(output),
    ])
    return output


def _segment_clip(
    text: str, voice: str, target_duration: float, workdir: Path, tag: str,
) -> tuple[Path, float] | None:
    """Sintetiza a fala do trecho e ajusta a velocidade pra caber (aprox.)
    no tempo original. Retorna (caminho, duração real após o ajuste)."""
    raw = synthesize(text, voice, workdir / f"{tag}_raw.mp3")
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
    segments: list[TranscriptSegment], voice: str, workdir: Path,
) -> Path:
    """Gera uma trilha de narração de IA contínua, sincronizada por trecho.

    Sempre que possível, cada trecho novo é realinhado ao `start` original
    (insere silêncio se a narração de IA está adiantada); se um trecho
    anterior estourou o tempo mesmo com o `atempo` limitado, o próximo
    começa colado, sem esperar — evita que o desvio se acumule ao longo do
    vídeo inteiro em vez de corrigir só no ponto onde ele aconteceu.
    """
    pieces: list[Path] = []
    cursor = 0.0
    for i, seg in enumerate(segments):
        text = seg.text.strip()
        if not text:
            continue
        gap = seg.start - cursor
        if gap > 0.02:
            pieces.append(_silence_clip(gap, workdir / f"gap_{i:04d}.wav"))
            cursor += gap
        result = _segment_clip(text, voice, seg.duration, workdir, f"seg_{i:04d}")
        if result is None:
            logger.warning("Narração do trecho %d falhou; seguindo sem ele.", i)
            continue
        clip, actual_duration = result
        pieces.append(clip)
        cursor += actual_duration
    if not pieces:
        raise AutoShortsError("Nenhum trecho de narração foi gerado.")
    return concat_same_encoding(pieces, workdir / "narracao_completa.wav", workdir)


def mux_final_audio(
    video_path: str | Path,
    narration_track: str | Path,
    background_track: str | Path | None,
    output: str | Path,
    duration: float,
    background_volume: int = 70,
) -> Path:
    """Troca a trilha de áudio do vídeo original pela narração de IA (+
    música/efeitos de fundo opcionais), sem reencodar o vídeo (`-c:v copy`).
    """
    output = Path(output)
    inputs = ["-i", str(video_path), "-i", str(narration_track)]
    if background_track is not None:
        vol = max(0.0, min(background_volume / 100.0, 1.5))
        inputs += ["-i", str(background_track)]
        audio_graph = (
            f"[1:a]volume=1.0[narr];[2:a]volume={vol:.2f}[bg];"
            f"[narr][bg]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
            f"apad,atrim=0:{duration:.3f},asetpts=N/SR/TB[aout]"
        )
    else:
        audio_graph = f"[1:a]apad,atrim=0:{duration:.3f},asetpts=N/SR/TB[aout]"
    run_ffmpeg([
        *inputs,
        "-filter_complex", audio_graph,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output),
    ], timeout=3600)
    logger.info("Vídeo redublado exportado: %s", output)
    return output
