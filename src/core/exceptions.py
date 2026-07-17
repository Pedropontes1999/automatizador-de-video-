"""Exceções específicas do AUTO SHORTS AI.

Uma hierarquia própria permite tratamento de erros granular sem capturar
`Exception` genérico em todo lugar.
"""
from __future__ import annotations


class AutoShortsError(Exception):
    """Erro base da aplicação. Toda exceção do projeto herda desta."""


class FFmpegError(AutoShortsError):
    """FFmpeg/FFprobe ausente ou execução com falha."""


class DownloadError(AutoShortsError):
    """Falha ao baixar vídeo do YouTube (yt-dlp)."""


class TranscriptionError(AutoShortsError):
    """Falha na transcrição com Whisper."""


class AIAnalysisError(AutoShortsError):
    """Falha na análise via Ollama (offline, modelo ausente, JSON inválido)."""


class VideoProcessingError(AutoShortsError):
    """Falha no reenquadramento, efeitos ou exportação."""


class TaskCancelledError(AutoShortsError):
    """Tarefa cancelada pelo usuário (fluxo de controle, não é um erro real)."""
