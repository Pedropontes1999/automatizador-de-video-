"""Pipeline de Redublagem por IA: transcreve a narração original, separa a
música/efeitos de fundo (Demucs) e gera uma nova narração por IA
sincronizada por trecho, substituindo só a voz do narrador humano.

Ao contrário do `ShortsPipeline`/`VideoEditPipeline`, o vídeo em si não é
reeditado nem reencodado — só a trilha de áudio é trocada (`-c:v copy`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.ai.transcriber import WhisperTranscriber
from src.audio.extractor import extract_audio_hq
from src.audio.redub_builder import build_narration_track, mux_final_audio
from src.audio.vocal_separator import separate_background
from src.config.settings import Settings
from src.core.exceptions import AutoShortsError
from src.core.task_manager import TaskControl
from src.utils import ffmpeg_utils
from src.utils.logger import get_logger
from src.utils.paths import new_temp_dir, project_output_dir, sanitize_filename
from src.video.downloader import download_video, is_youtube_url

logger = get_logger("redub")


@dataclass
class RedubCallbacks:
    """Callbacks para a GUI acompanhar o processamento em tempo real."""

    on_progress: Callable[[int, str], None] = lambda pct, msg: None


@dataclass
class RedubPipeline:
    """Orquestra a troca da narração de um vídeo já pronto."""

    settings: Settings
    callbacks: RedubCallbacks = field(default_factory=RedubCallbacks)

    def run(self, source: str, control: TaskControl) -> Path:
        s = self.settings
        cb = self.callbacks
        control.checkpoint()

        cb.on_progress(3, "Resolvendo vídeo de origem...")
        if is_youtube_url(source):
            video_path = download_video(
                source, progress=lambda p, m: cb.on_progress(3 + int(p * 0.07), m),
            )
        else:
            video_path = Path(source)
        info = ffmpeg_utils.video_info(video_path)
        temp_dir = new_temp_dir("redub")
        control.checkpoint()

        cb.on_progress(12, "Extraindo áudio original...")
        audio_path = extract_audio_hq(video_path, temp_dir)
        control.checkpoint()

        cb.on_progress(18, "Transcrevendo a narração original com Whisper...")
        transcriber = WhisperTranscriber(s.whisper_model, s.use_gpu)
        transcription = transcriber.transcribe(
            audio_path, s.language, progress=lambda m: cb.on_progress(25, m),
        )
        if not transcription.segments:
            raise AutoShortsError(
                "Não foi possível identificar falas nesse vídeo."
            )
        control.checkpoint()

        background_path = None
        if s.redub_keep_background:
            cb.on_progress(40, "Separando música/efeitos de fundo (pode demorar)...")
            background_path = separate_background(audio_path, temp_dir, use_gpu=s.use_gpu)
        control.checkpoint()

        cb.on_progress(60, "Gerando a nova narração por IA (sincronizada por trecho)...")
        narration_track = build_narration_track(
            transcription.segments, s.redub_voice, temp_dir,
        )
        control.checkpoint()

        cb.on_progress(85, "Montando o vídeo final (pode demorar alguns minutos)...")
        output_dir = project_output_dir(video_path.stem)
        output_path = output_dir / f"{sanitize_filename(video_path.stem)}_redublado.mp4"
        mux_final_audio(
            video_path, narration_track, background_path, output_path,
            duration=info["duration"], background_volume=s.redub_background_volume,
        )

        cb.on_progress(100, f"Concluído! Vídeo redublado salvo em {output_path}")
        return output_path
