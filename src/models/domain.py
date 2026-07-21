"""Modelos de domínio do AUTO SHORTS AI.

Dataclasses puras (sem dependência de GUI ou banco) que trafegam entre as
camadas: transcrição -> análise IA -> edição -> exportação.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TranscriptWord:
    """Uma palavra com carimbos de tempo (para legendas sincronizadas)."""

    text: str
    start: float  # segundos
    end: float


@dataclass
class TranscriptSegment:
    """Uma frase/segmento da transcrição."""

    index: int
    text: str
    start: float
    end: float
    words: list[TranscriptWord] = field(default_factory=list)
    # Sinais de confiança que o próprio Whisper reporta por segmento (ver
    # openai-whisper `DecodingResult`). Usados na Redublagem pra descartar
    # trechos que provavelmente não são fala real do narrador (efeito
    # sonoro, música, ruído) e que o Whisper "alucinou" como texto.
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0
    compression_ratio: float = 0.0

    @property
    def duration(self) -> float:
        """Duração do segmento em segundos."""
        return self.end - self.start

    @property
    def is_confident_speech(self) -> bool:
        """Heurística (mesmos limiares padrão do Whisper) pra saber se o
        segmento é fala de verdade, e não ruído/efeito/música mal
        transcrito como texto."""
        return (
            self.no_speech_prob < 0.6
            and self.avg_logprob > -1.0
            and self.compression_ratio < 2.4
        )


@dataclass
class Transcription:
    """Transcrição completa de um vídeo."""

    language: str
    segments: list[TranscriptSegment] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Texto completo concatenado."""
        return " ".join(s.text.strip() for s in self.segments)

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário (salvo como JSON no projeto)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcription":
        """Reconstrói a transcrição a partir de JSON."""
        segments = [
            TranscriptSegment(
                index=s["index"], text=s["text"], start=s["start"], end=s["end"],
                words=[TranscriptWord(**w) for w in s.get("words", [])],
            )
            for s in data.get("segments", [])
        ]
        return cls(language=data.get("language", "auto"), segments=segments)


@dataclass
class CutCandidate:
    """Um trecho escolhido pela IA para virar Short.

    Contém tudo que a IA devolve (tempos, título, nota) mais o resultado da
    edição (caminho do arquivo exportado).
    """

    start: float
    end: float
    title: str
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    category: str = "geral"
    score: int = 0                       # 0-100
    score_breakdown: dict[str, int] = field(default_factory=dict)
    reason: str = ""                     # justificativa da IA
    output_path: str | None = None       # preenchido após exportação
    status: str = "pending"              # pending | processing | done | error

    @property
    def duration(self) -> float:
        """Duração do corte em segundos."""
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        """Serializa para persistência (SQLite/JSON)."""
        return asdict(self)


@dataclass
class Project:
    """Um trabalho completo: vídeo de origem + transcrição + cortes."""

    id: int | None = None
    source_path: str = ""
    source_url: str | None = None
    title: str = ""
    duration: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    transcription: Transcription | None = None
    cuts: list[CutCandidate] = field(default_factory=list)
    status: str = "new"  # new | transcribing | analyzing | cutting | done | error
