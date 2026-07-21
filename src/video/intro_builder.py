"""Bloco de abertura do Editor de Vídeo: narração por IA e/ou transição de
estática de TV, concatenados antes do vídeo original.

Todo clipe intermediário (narração, estática) é gerado com os mesmos
parâmetros de codificação, o que permite juntá-los entre si via concat
demuxer com `-c copy` (rápido, sem perda). Só a junção final com o vídeo
original precisa de reencode, já que o vídeo de origem pode ter
codec/fps/resolução arbitrários.
"""
from __future__ import annotations

from pathlib import Path

from src.utils.ffmpeg_utils import gpu_encoder_args, run_ffmpeg
from src.utils.logger import get_logger

logger = get_logger("intro_builder")


def _encoder_args(use_gpu: bool, crf: int) -> list[str]:
    if use_gpu:
        gpu_args = gpu_encoder_args(crf)
        if gpu_args is not None:
            return gpu_args
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]


def extract_freeze_frame(
    video_path: str | Path, output: str | Path, width: int, height: int,
) -> Path:
    """Extrai o primeiro frame do vídeo original, para servir de fundo
    parado (imagem congelada) enquanto a narração fala."""
    output = Path(output)
    run_ffmpeg([
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=disable,setsar=1",
        str(output),
    ])
    return output


def build_narration_clip(
    narration_audio: str | Path,
    duration: float,
    background_image: str | Path,
    width: int,
    height: int,
    fps: float,
    output: str | Path,
    use_gpu: bool = True,
    music_path: str | Path | None = None,
    music_volume: int = 20,
) -> Path:
    """Imagem parada (frame congelado do próprio vídeo) com a narração e,
    opcionalmente, uma música de fundo tocando por baixo (volume reduzido).
    """
    output = Path(output)
    inputs = [
        "-loop", "1", "-t", f"{duration:.3f}", "-i", str(background_image),
        "-i", str(narration_audio),
    ]
    video_graph = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=disable,"
        f"setsar=1,format=yuv420p[v]"
    )
    if music_path is not None:
        # -stream_loop -1: repete a música indefinidamente caso ela seja
        # mais curta que a narração; o "-shortest" no final corta tudo no
        # fim do vídeo/narração de qualquer forma.
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]
        vol = max(0.0, min(music_volume / 100.0, 1.0))
        audio_graph = (
            f"[2:a]volume={vol:.2f}[bgm];"
            f"[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
        )
    else:
        audio_graph = "[1:a]anull[a]"
    run_ffmpeg([
        *inputs,
        "-filter_complex", f"{video_graph};{audio_graph}",
        "-map", "[v]", "-map", "[a]",
        *_encoder_args(use_gpu, 20),
        "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest",
        str(output),
    ])
    logger.info(
        "Clipe de narração gerado (%.1fs%s): %s",
        duration, " + música de fundo" if music_path else "", output.name,
    )
    return output


def build_static_clip(
    duration: float,
    width: int,
    height: int,
    fps: float,
    output: str | Path,
    use_gpu: bool = True,
    audio_amplitude: float = 0.3,
) -> Path:
    """Estática de TV colorida (ruído RGB) com o clássico chiado de áudio.

    `geq=random(idx)` usa o mesmo padrão de ruído independente do `idx`
    (testado no FFmpeg 8.1.2 — R/G/B saíam idênticos, ou seja, cinza). O
    filtro `noise` com uma seed por componente (`c0s`/`c1s`/`c2s`) é quem de
    fato descorrelaciona os canais e gera ruído colorido de verdade.
    """
    output = Path(output)
    run_ffmpeg([
        "-f", "lavfi", "-t", f"{duration:.3f}",
        "-i", f"color=c=gray:s={width}x{height}:rate={fps}",
        "-f", "lavfi", "-t", f"{duration:.3f}",
        "-i", f"anoisesrc=color=white:amplitude={audio_amplitude}:sample_rate=48000",
        "-vf",
        "format=rgb24,"
        "noise=c0s=11:c0f=t+u:c1s=22:c1f=t+u:c2s=33:c2f=t+u:alls=100,"
        "eq=contrast=2.2:saturation=1.6,"
        "format=yuv420p",
        *_encoder_args(use_gpu, 20),
        "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(output),
    ])
    logger.info("Clipe de estática gerado (%.1fs): %s", duration, output.name)
    return output


def concat_same_encoding(clips: list[Path], output: str | Path, workdir: Path) -> Path:
    """Concatena clipes já codificados com os mesmos parâmetros (stream copy)."""
    output = Path(output)
    list_file = workdir / "intro_concat.txt"
    lines = "\n".join(f"file '{str(c).replace(chr(92), '/')}'" for c in clips)
    list_file.write_text(lines, encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output)])
    return output


def concat_intro_and_video(
    intro: str | Path,
    main_video: str | Path,
    output: str | Path,
    width: int,
    height: int,
    fps: float,
    use_gpu: bool = True,
    crf: int = 20,
) -> Path:
    """Junta a abertura com o vídeo original num único MP4 (reencode completo).

    Normaliza escala/fps/formato e áudio de ambos os inputs antes do
    `concat`, já que o vídeo original pode ter parâmetros diferentes dos
    clipes de abertura (que nós mesmos geramos).
    """
    output = Path(output)
    graph = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=disable,"
        f"setsar=1,fps={fps},format=yuv420p[v0];"
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=disable,"
        f"setsar=1,fps={fps},format=yuv420p[v1];"
        f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a0];"
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a1];"
        f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[vout][aout]"
    )
    run_ffmpeg([
        "-i", str(intro), "-i", str(main_video),
        "-filter_complex", graph,
        "-map", "[vout]", "-map", "[aout]",
        *_encoder_args(use_gpu, crf),
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output),
    ], timeout=3600)
    logger.info("Vídeo editado exportado: %s", output)
    return output
