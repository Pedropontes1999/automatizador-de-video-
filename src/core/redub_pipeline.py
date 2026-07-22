"""Pipeline de Redublagem por IA, em duas etapas:

1. `prepare()` — transcreve a narração original e separa a música/efeitos de
   fundo (Demucs), devolvendo os trechos por escrito pra GUI mostrar ao
   usuário.
2. `generate()` — recebe os mesmos trechos, com o texto (possivelmente já
   reescrito pelo usuário) no lugar da transcrição original, gera a nova
   narração por IA sincronizada por trecho e substitui a voz no vídeo.

Separar em duas etapas existe porque o objetivo da Redublagem não é só
trocar o timbre da voz: o usuário reescreve a narração com outras palavras
entre as duas etapas, pra não ficar uma cópia da fala original.

Ao contrário do `ShortsPipeline`/`VideoEditPipeline`, o vídeo em si não é
reeditado nem reencodado — só a trilha de áudio é trocada (`-c:v copy`).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from src.ai.transcriber import WhisperTranscriber
from src.audio.extractor import extract_audio_hq
from src.audio.redub_builder import build_narration_track, mux_final_audio
from src.audio.vocal_separator import separate_vocals
from src.config.settings import Settings
from src.core.exceptions import AutoShortsError
from src.core.task_manager import TaskControl
from src.models.domain import TranscriptSegment
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
class RedubPreparation:
    """Estado entre as duas etapas: o vídeo já foi baixado/lido, a voz
    separada e transcrita — falta só o usuário revisar/reescrever o texto de
    cada trecho antes de `generate()` sintetizar a nova narração."""

    video_path: Path
    temp_dir: Path
    duration: float
    segments: list[TranscriptSegment]
    background_path: Path | None


@dataclass
class RedubPipeline:
    """Orquestra a troca da narração de um vídeo já pronto."""

    settings: Settings
    callbacks: RedubCallbacks = field(default_factory=RedubCallbacks)

    def prepare(self, source: str, control: TaskControl) -> RedubPreparation:
        """Baixa/lê o vídeo, separa a voz do resto do áudio e transcreve a
        narração original. Não gera nenhuma voz nova — só entrega o texto
        pra revisão do usuário."""
        s = self.settings
        cb = self.callbacks
        control.checkpoint()

        cb.on_progress(5, "Resolvendo vídeo de origem...")
        if is_youtube_url(source):
            video_path = download_video(
                source, progress=lambda p, m: cb.on_progress(5 + int(p * 0.15), m),
            )
        else:
            video_path = Path(source)
        info = ffmpeg_utils.video_info(video_path)
        temp_dir = new_temp_dir("redub")
        control.checkpoint()

        cb.on_progress(25, "Extraindo áudio original...")
        audio_path = extract_audio_hq(video_path, temp_dir)
        control.checkpoint()

        # Separa a voz (Demucs) ANTES de transcrever: transcrever o áudio
        # cru faz o Whisper "ouvir" fala em música/efeitos sonoros e tratar
        # esse texto alucinado como narração. Transcrevendo só o stem
        # "vocals" (e depois filtrando por confiança abaixo), a Redublagem
        # troca só o que é voz de verdade, não o áudio do vídeo inteiro.
        cb.on_progress(40, "Separando a voz do resto do áudio (pode demorar)...")
        separated = separate_vocals(audio_path, temp_dir, use_gpu=s.use_gpu)
        vocals_path = separated.vocals if separated else audio_path
        background_path = separated.no_vocals if (separated and s.redub_keep_background) else None
        control.checkpoint()

        cb.on_progress(65, "Transcrevendo a narração original com Whisper...")
        transcriber = WhisperTranscriber(s.whisper_model, s.use_gpu)
        transcription = transcriber.transcribe(
            vocals_path, s.language, progress=lambda m: cb.on_progress(70, m),
        )
        segments = [seg for seg in transcription.segments if seg.is_confident_speech]
        dropped = len(transcription.segments) - len(segments)
        if dropped:
            logger.info(
                "%d trecho(s) descartado(s) por baixa confiança de fala "
                "(provável ruído/efeito/música, não narração).", dropped,
            )
        if not segments:
            raise AutoShortsError(
                "Não foi possível identificar falas nesse vídeo."
            )
        control.checkpoint()

        cb.on_progress(100, "Transcrição pronta — revise o texto antes de gerar a nova voz.")
        return RedubPreparation(
            video_path=video_path, temp_dir=temp_dir, duration=info["duration"],
            segments=segments, background_path=background_path,
        )

    def generate(
        self, preparation: RedubPreparation, texts: list[str], control: TaskControl,
    ) -> Path:
        """Sintetiza a nova narração a partir de `texts` (um item por trecho
        de `preparation.segments`, na mesma ordem) e troca a voz no vídeo."""
        s = self.settings
        cb = self.callbacks
        control.checkpoint()

        if len(texts) != len(preparation.segments):
            raise AutoShortsError(
                f"O texto revisado tem {len(texts)} linha(s), mas o vídeo "
                f"original tem {len(preparation.segments)} trecho(s) falados. "
                "Não apague nem quebre linhas — edite só o conteúdo de cada uma."
            )
        segments = [
            replace(seg, text=text.strip())
            for seg, text in zip(preparation.segments, texts)
        ]

        cb.on_progress(10, "Gerando a nova narração por IA (sincronizada por trecho)...")
        narration_track = build_narration_track(segments, s.redub_voice, preparation.temp_dir)
        control.checkpoint()

        cb.on_progress(60, "Montando o vídeo final (pode demorar alguns minutos)...")
        output_dir = project_output_dir(preparation.video_path.stem)
        output_path = output_dir / f"{sanitize_filename(preparation.video_path.stem)}_redublado.mp4"
        mux_final_audio(
            preparation.video_path, narration_track, preparation.background_path, output_path,
            duration=preparation.duration, background_volume=s.redub_background_volume,
            use_gpu=s.use_gpu, crf=s.quality_crf,
        )

        cb.on_progress(100, f"Concluído! Vídeo redublado salvo em {output_path}")
        return output_path
