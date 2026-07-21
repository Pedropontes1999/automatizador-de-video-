"""Transcrição de áudio com Whisper (OpenAI) rodando localmente.

Gera segmentos por frase com timestamps por palavra — essencial para as
legendas sincronizadas estilo TikTok.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from src.core.exceptions import TranscriptionError
from src.models.domain import Transcription, TranscriptSegment, TranscriptWord
from src.utils.logger import get_logger

logger = get_logger("transcriber")

ProgressFn = Callable[[str], None]


class WhisperTranscriber:
    """Encapsula o carregamento do modelo Whisper e a transcrição.

    O modelo é carregado apenas uma vez (lazy) e reutilizado entre vídeos.
    """

    def __init__(self, model_name: str = "small", use_gpu: bool = True) -> None:
        self.model_name = model_name
        self.use_gpu = use_gpu
        self._model = None

    # ------------------------------------------------------------------ #
    def _load_model(self):
        """Carrega o modelo Whisper na GPU (se disponível) ou CPU."""
        if self._model is not None:
            return self._model
        try:
            import torch
            import whisper
        except ImportError as exc:
            raise TranscriptionError(
                "Whisper não instalado. Rode: pip install openai-whisper"
            ) from exc

        device = "cuda" if (self.use_gpu and torch.cuda.is_available()) else "cpu"
        logger.info("Carregando Whisper '%s' em %s...", self.model_name, device)
        self._model = whisper.load_model(self.model_name, device=device)
        return self._model

    # ------------------------------------------------------------------ #
    def transcribe(
        self,
        audio_path: str | Path,
        language: str = "auto",
        progress: ProgressFn | None = None,
    ) -> Transcription:
        """Transcreve o áudio e retorna segmentos com palavras temporizadas.

        Args:
            audio_path: caminho do arquivo de áudio (wav/mp3).
            language: código ISO ('pt', 'en', 'es') ou 'auto' para detectar.
            progress: callback opcional para mensagens de status na GUI.
        """
        model = self._load_model()
        if progress:
            progress("Transcrevendo áudio com Whisper...")
        try:
            result = model.transcribe(
                str(audio_path),
                language=None if language == "auto" else language,
                word_timestamps=True,
                verbose=None,
                fp16=self.use_gpu,
            )
        except Exception as exc:  # noqa: BLE001 - whisper lança tipos variados
            raise TranscriptionError(f"Falha na transcrição: {exc}") from exc

        segments: list[TranscriptSegment] = []
        for i, seg in enumerate(result.get("segments", [])):
            words = [
                TranscriptWord(
                    text=w.get("word", "").strip(),
                    start=float(w.get("start", seg["start"])),
                    end=float(w.get("end", seg["end"])),
                )
                for w in seg.get("words", [])
                if w.get("word", "").strip()
            ]
            segments.append(
                TranscriptSegment(
                    index=i,
                    text=seg.get("text", "").strip(),
                    start=float(seg["start"]),
                    end=float(seg["end"]),
                    words=words,
                    no_speech_prob=float(seg.get("no_speech_prob", 0.0)),
                    avg_logprob=float(seg.get("avg_logprob", 0.0)),
                    compression_ratio=float(seg.get("compression_ratio", 0.0)),
                )
            )

        transcription = Transcription(
            language=result.get("language", language), segments=segments,
        )
        logger.info(
            "Transcrição concluída: %d segmentos, idioma '%s'.",
            len(segments), transcription.language,
        )
        return transcription

    # ------------------------------------------------------------------ #
    @staticmethod
    def save_json(transcription: Transcription, path: str | Path) -> None:
        """Salva a transcrição em JSON (formato do projeto)."""
        Path(path).write_text(
            json.dumps(transcription.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Transcrição salva em %s", path)
