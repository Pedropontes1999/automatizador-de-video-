"""Pipeline do Editor de Vídeo: edita um vídeo completo sem cortar em Shorts.

Etapas:
1. (opcional) Download do YouTube (yt-dlp)
2. Narração por IA no início (edge-tts) — opcional
3. Transição de estática de TV — opcional
4. Concatena a abertura (narração + estática) com o vídeo original e exporta
   um único MP4, preservando o formato/resolução de origem.

Ao contrário do `ShortsPipeline`, não há transcrição, análise viral nem
reenquadramento 9:16: o vídeo original é mantido inteiro, só ganha uma
abertura na frente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.audio.tts import audio_duration, synthesize
from src.config.settings import Settings
from src.core.exceptions import VideoProcessingError
from src.core.task_manager import TaskControl
from src.utils import ffmpeg_utils
from src.utils.logger import get_logger
from src.utils.paths import new_temp_dir, project_output_dir, sanitize_filename
from src.video.downloader import download_video, is_youtube_url
from src.video.intro_builder import (
    build_narration_clip,
    build_static_clip,
    concat_intro_and_video,
    concat_same_encoding,
    extract_freeze_frame,
)

logger = get_logger("video_editor")


@dataclass
class VideoEditCallbacks:
    """Callbacks para a GUI acompanhar o processamento em tempo real."""

    on_progress: Callable[[int, str], None] = lambda pct, msg: None


@dataclass
class VideoEditPipeline:
    """Orquestra a edição de um vídeo completo com abertura opcional."""

    settings: Settings
    callbacks: VideoEditCallbacks = field(default_factory=VideoEditCallbacks)

    def run(self, source: str, control: TaskControl) -> Path:
        """Executa o pipeline completo para um arquivo local ou link do YouTube."""
        s = self.settings
        cb = self.callbacks
        control.checkpoint()

        if not s.editor_narration_enabled and not s.editor_static_enabled:
            raise VideoProcessingError(
                "Ative a narração e/ou a transição de estática antes de processar."
            )

        cb.on_progress(3, "Resolvendo vídeo de origem...")
        if is_youtube_url(source):
            video_path = download_video(
                source, progress=lambda p, m: cb.on_progress(3 + int(p * 0.1), m),
            )
        else:
            video_path = Path(source)
        info = ffmpeg_utils.video_info(video_path)
        width = info["width"] - info["width"] % 2
        height = info["height"] - info["height"] % 2
        fps = round(info["fps"], 2) or 30.0
        temp_dir = new_temp_dir("edit")
        control.checkpoint()

        clips: list[Path] = []

        if s.editor_narration_enabled and s.editor_narration_text.strip():
            cb.on_progress(15, "Gerando narração com IA (Microsoft)...")
            narration_audio = synthesize(
                s.editor_narration_text, s.editor_narration_voice,
                temp_dir / "narracao.mp3",
            )
            if narration_audio is not None:
                duration = audio_duration(narration_audio)
                cb.on_progress(25, "Montando abertura com a narração...")
                freeze_frame = extract_freeze_frame(
                    video_path, temp_dir / "freeze.png", width, height,
                )
                music_path = (
                    s.editor_music_path
                    if s.editor_music_path and Path(s.editor_music_path).exists()
                    else None
                )
                clips.append(build_narration_clip(
                    narration_audio, duration, freeze_frame, width, height, fps,
                    temp_dir / "intro_narracao.mp4", use_gpu=s.use_gpu,
                    music_path=music_path, music_volume=s.editor_music_volume,
                ))
            else:
                logger.warning("Narração indisponível; abertura seguirá sem ela.")
        control.checkpoint()

        if s.editor_static_enabled:
            cb.on_progress(35, "Gerando transição de estática de TV...")
            clips.append(build_static_clip(
                float(s.editor_static_seconds), width, height, fps,
                temp_dir / "intro_estatica.mp4", use_gpu=s.use_gpu,
            ))
        control.checkpoint()

        if not clips:
            raise VideoProcessingError(
                "Nenhuma abertura foi gerada: a narração falhou e a estática "
                "está desligada."
            )

        if len(clips) == 1:
            intro = clips[0]
        else:
            cb.on_progress(40, "Juntando narração e estática...")
            intro = concat_same_encoding(clips, temp_dir / "intro.mp4", temp_dir)
        control.checkpoint()

        cb.on_progress(45, "Renderizando vídeo final (pode demorar alguns minutos)...")
        output_dir = project_output_dir(video_path.stem)
        output_path = output_dir / f"{sanitize_filename(video_path.stem)}_editado.mp4"
        concat_intro_and_video(
            intro, video_path, output_path, width, height, fps,
            use_gpu=s.use_gpu, crf=s.quality_crf,
        )

        cb.on_progress(100, f"Concluído! Vídeo editado salvo em {output_path}")
        return output_path
