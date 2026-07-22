"""Pipeline standalone de Transcrição: baixa/lê um vídeo, extrai o áudio e
transcreve com Whisper — sem cortes nem redublagem.

Alimenta a modal de exportação de transcrição (visualizar, editar, copiar,
exportar TXT/DOCX/MD e gerar prompt de roteiro pra IA). Reaproveita o mesmo
cache de transcrição usado pelo `ShortsPipeline` (chave = vídeo + modelo
Whisper), então transcrever o mesmo vídeo duas vezes não repete o trabalho.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.ai.transcriber import WhisperTranscriber
from src.audio.extractor import extract_audio
from src.config.settings import Settings
from src.core.exceptions import AutoShortsError
from src.models.domain import Transcription
from src.utils.logger import get_logger
from src.utils.paths import new_temp_dir, project_output_dir, transcript_cache_path
from src.video.downloader import download_video, is_youtube_url

logger = get_logger("transcribe_pipeline")

ProgressFn = Callable[[str], None]


@dataclass
class TranscribeCallbacks:
    """Callback para a GUI acompanhar o andamento (sem percentual: só a
    extração de áudio e o Whisper em si, nenhuma etapa reporta progresso
    granular)."""

    on_progress: ProgressFn = lambda msg: None


@dataclass
class TranscribePipeline:
    """Orquestra só a transcrição de um vídeo, sem gerar cortes/redublagem."""

    settings: Settings
    callbacks: TranscribeCallbacks = field(default_factory=TranscribeCallbacks)

    def run(self, source: str) -> tuple[Transcription, str]:
        """Retorna (transcrição, título do vídeo)."""
        s = self.settings
        cb = self.callbacks

        cb.on_progress("Resolvendo vídeo de origem...")
        if is_youtube_url(source):
            video_path = download_video(source, progress=lambda p, m: cb.on_progress(m))
        else:
            video_path = Path(source)
        if not video_path.exists():
            raise AutoShortsError(f"Vídeo não encontrado: {video_path}")

        temp_dir = new_temp_dir("transcript")
        cb.on_progress("Extraindo áudio...")
        audio_path = extract_audio(video_path, temp_dir)

        cache_file = transcript_cache_path(video_path, s.whisper_model)
        output_dir = project_output_dir(video_path.stem)
        transcriber = WhisperTranscriber(s.whisper_model, s.use_gpu)

        cached = WhisperTranscriber.load_cached(cache_file, output_dir / "transcricao.json")
        if cached is not None:
            cb.on_progress("Transcrição anterior encontrada — reutilizando.")
            transcription = cached
        else:
            cb.on_progress("Transcrevendo com Whisper (pode demorar)...")
            transcription = transcriber.transcribe(
                audio_path, s.language, progress=cb.on_progress,
            )
            transcriber.save_json(transcription, cache_file)
            transcriber.save_json(transcription, output_dir / "transcricao.json")

        cb.on_progress("Transcrição concluída.")
        return transcription, video_path.stem
