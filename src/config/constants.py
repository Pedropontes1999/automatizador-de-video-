"""Constantes globais do AUTO SHORTS AI.

Centraliza caminhos, formatos e valores padrão para evitar "números mágicos"
espalhados pelo código.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
SRC_DIR: Path = PROJECT_ROOT / "src"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
TEMP_DIR: Path = PROJECT_ROOT / "temp"
CACHE_DIR: Path = PROJECT_ROOT / "cache"
OUTPUT_DIR: Path = PROJECT_ROOT / "output"
DOWNLOADS_DIR: Path = PROJECT_ROOT / "downloads"
ASSETS_DIR: Path = PROJECT_ROOT / "assets"
FONTS_DIR: Path = ASSETS_DIR / "fonts"
ICONS_DIR: Path = ASSETS_DIR / "icons"
CONFIG_FILE: Path = PROJECT_ROOT / "config.json"
DATABASE_FILE: Path = PROJECT_ROOT / "autoshorts.db"
PLUGINS_DIR: Path = SRC_DIR / "plugins"

# Vídeos editados na aba Editor (marca d'água / narração, sem corte por IA).
EDITOR_OUTPUT_DIR: Path = OUTPUT_DIR / "editados"

# Vídeos com trechos removidos manualmente na aba Cortar Vídeo.
TRIM_OUTPUT_DIR: Path = OUTPUT_DIR / "cortados"

# Vídeos com marca d'água removida na aba Remover Marca d'Água.
WATERMARK_OUTPUT_DIR: Path = OUTPUT_DIR / "sem_marca"

REQUIRED_FOLDERS: tuple[Path, ...] = (
    LOGS_DIR, TEMP_DIR, CACHE_DIR, OUTPUT_DIR, DOWNLOADS_DIR,
    ASSETS_DIR, FONTS_DIR, ICONS_DIR, EDITOR_OUTPUT_DIR, TRIM_OUTPUT_DIR,
    WATERMARK_OUTPUT_DIR,
)

# ---------------------------------------------------------------------------
# Vídeo / Exportação
# ---------------------------------------------------------------------------
EXPORT_WIDTH: int = 1080
EXPORT_HEIGHT: int = 1920
EXPORT_FPS: int = 30
EXPORT_VIDEO_CODEC: str = "libx264"
EXPORT_AUDIO_CODEC: str = "aac"
EXPORT_CONTAINER: str = "mp4"
SUPPORTED_VIDEO_EXTENSIONS: tuple[str, ...] = (
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts", ".flv",
)

# ---------------------------------------------------------------------------
# Categorias de vídeo
# ---------------------------------------------------------------------------
# Cada categoria ajusta o pipeline ao tipo de conteúdo (rastreamento de rosto,
# limpeza de silêncio, detecção de picos de ação). "geral" mantém o
# comportamento clássico voltado a vídeos de pessoas falando.
VIDEO_CATEGORIES: dict[str, str] = {
    "geral": "🎬 Geral",
    "anime": "🎌 Anime",
    "game": "🎮 Game",
    "carros": "🚗 Carros",
}
DEFAULT_VIDEO_CATEGORY: str = "geral"

# ---------------------------------------------------------------------------
# Cortes
# ---------------------------------------------------------------------------
DEFAULT_MIN_CUT_SECONDS: int = 20
DEFAULT_MAX_CUT_SECONDS: int = 90
DEFAULT_MAX_CUTS: int = 10
MIN_VIRAL_SCORE: int = 55  # nota mínima (0-100) para um trecho virar corte

# ---------------------------------------------------------------------------
# IA
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL: str = "qwen2.5:3b"
OLLAMA_SUGGESTED_MODELS: tuple[str, ...] = (
    "qwen2.5:3b", "qwen2.5:7b", "llama3.1:8b", "mistral:7b", "gemma2:9b",
)
WHISPER_DEFAULT_MODEL: str = "small"
WHISPER_MODELS: tuple[str, ...] = ("tiny", "base", "small", "medium", "large-v3")
SUPPORTED_LANGUAGES: dict[str, str] = {
    "auto": "Detectar automaticamente",
    "pt": "Português",
    "en": "Inglês",
    "es": "Espanhol",
}

# ---------------------------------------------------------------------------
# Estilo / identidade visual
# ---------------------------------------------------------------------------
# Selo do canal (gerado a partir de nome/@/foto na página Estilo)
CHANNEL_BADGE_FILE: Path = ASSETS_DIR / "channel_badge.png"
BADGE_POSITIONS: dict[str, str] = {
    "bottom": "Rodapé (faixa desfocada de baixo)",
    "top": "Topo (faixa desfocada de cima)",
}

# Enquadramento 9:16 do modo anime
ANIME_FRAMING: dict[str, str] = {
    "blur": "Vídeo inteiro + fundo desfocado (estilo canais de corte)",
    "crop": "Crop central preenchendo a tela",
}

WATERMARK_POSITIONS: dict[str, str] = {
    "top-left": "Canto superior esquerdo",
    "top-right": "Canto superior direito",
    "bottom-left": "Canto inferior esquerdo",
    "bottom-right": "Canto inferior direito",
}
SUPPORTED_IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")
SUPPORTED_AUDIO_EXTENSIONS: tuple[str, ...] = (
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma",
    ".mp4", ".mkv", ".webm", ".mov",  # containers de vídeo: usa só a trilha de áudio
)

# ---------------------------------------------------------------------------
# Narração (TTS via XTTS v2/Coqui — local, offline, voz bem mais natural)
# ---------------------------------------------------------------------------
# Voz "edge:<nome curto da voz Microsoft Edge TTS>" usa a nuvem da
# Microsoft: grátis, sem chave de API, rápida e sem precisar de GPU — mas
# precisa de internet e não aceita clonagem de voz (`voice_reference` é
# ignorado pra essas vozes). Único motor/voz por pedido do usuário em
# 2026-07 (voz "Antônio", grave e natural — testada e aprovada; as vozes
# XTTS locais foram removidas da lista).
TTS_VOICES: dict[str, str] = {
    "edge:pt-BR-AntonioNeural": "Antônio (Edge TTS, grave e natural)",
}
TTS_DEFAULT_VOICE: str = "edge:pt-BR-AntonioNeural"

# ---------------------------------------------------------------------------
# Legendas
# ---------------------------------------------------------------------------
SUBTITLE_STYLES: tuple[str, ...] = (
    "TikTok", "Hormozi", "MrBeast", "Minimalista", "Podcast", "Gaming", "Cinema",
)
DEFAULT_SUBTITLE_STYLE: str = "TikTok"

# ---------------------------------------------------------------------------
# Silêncio / limpeza automática
# ---------------------------------------------------------------------------
SILENCE_THRESHOLD_DB: float = -35.0
MIN_SILENCE_SECONDS: float = 0.8
FILLER_WORDS_PT: tuple[str, ...] = ("ãh", "éh", "hum", "né", "tipo assim")

# ---------------------------------------------------------------------------
# Modo Humanizado (aba Editar Shorts): pequenas variações automáticas e
# sorteadas por renderização, pra duas exportações do mesmo vídeo nunca
# saírem tecnicamente idênticas (zoom/pan/cor/etc. — nunca efeitos chamativos)
# ---------------------------------------------------------------------------
HUMANIZE_ZOOM_MIN: float = 1.01
HUMANIZE_ZOOM_MAX: float = 1.08
HUMANIZE_ZOOM_SEGMENT_MIN_SECONDS: float = 2.0
HUMANIZE_ZOOM_SEGMENT_MAX_SECONDS: float = 5.0
HUMANIZE_PAN_DIRECTIONS: tuple[str, ...] = (
    "left_right", "right_left", "top_bottom", "bottom_top",
    "diagonal_tl_br", "diagonal_tr_bl",
)
HUMANIZE_SPEED_MIN: float = 0.998
HUMANIZE_SPEED_MAX: float = 1.002
HUMANIZE_GRAIN_MIN: float = 2.0   # %
HUMANIZE_GRAIN_MAX: float = 4.0   # %
HUMANIZE_COLOR_PRESETS: tuple[str, ...] = ("A", "B", "C")
