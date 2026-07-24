"""Criação e resolução de pastas do projeto."""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from src.config.constants import CACHE_DIR, OUTPUT_DIR, REQUIRED_FOLDERS, TEMP_DIR


def ensure_project_folders() -> None:
    """Cria automaticamente todas as pastas necessárias (idempotente)."""
    for folder in REQUIRED_FOLDERS:
        folder.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """Remove caracteres inválidos para nomes de arquivo no Windows/Linux."""
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip()
    # O corte por max_length precisa vir antes da limpeza final de bordas:
    # cortar depois pode deixar espaço/ponto no final (Windows não aceita
    # nomes de arquivo/pasta terminando em espaço ou ponto — e diferente do
    # Explorer, o FFmpeg não normaliza isso ao abrir o arquivo).
    clean = clean[:max_length].strip().rstrip(". ")
    return clean or "video"


def new_temp_dir(prefix: str = "job") -> Path:
    """Cria um diretório temporário único dentro de temp/."""
    path = TEMP_DIR / f"{prefix}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcript_cache_path(video_path: str | Path, whisper_model: str = "small") -> Path:
    """Caminho estável do cache de transcrição de um vídeo.

    Fica em cache/ (pasta interna, fora de output/) e é identificado pelo
    nome + tamanho do arquivo + modelo Whisper — assim sobrevive mesmo que o
    usuário apague a pasta de saída, e trocar de modelo gera nova transcrição.
    """
    video_path = Path(video_path)
    size = video_path.stat().st_size if video_path.exists() else 0
    key = hashlib.md5(
        f"{video_path.name}|{size}|{whisper_model}".encode("utf-8")
    ).hexdigest()[:16]
    folder = CACHE_DIR / "transcripts"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{key}.json"


def project_output_dir(video_title: str) -> Path:
    """Cria a pasta de saída de um projeto dentro de output/."""
    path = OUTPUT_DIR / sanitize_filename(video_title)
    path.mkdir(parents=True, exist_ok=True)
    return path
