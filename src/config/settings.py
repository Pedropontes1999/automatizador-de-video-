"""Gerenciador de configurações persistidas em config.json.

Carrega, valida e salva as preferências do usuário. Qualquer chave ausente
recebe o valor padrão, garantindo compatibilidade entre versões (auto-update).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from src.config import constants as C
from src.utils.logger import get_logger

logger = get_logger("settings")


@dataclass
class Settings:
    """Configurações do usuário com valores padrão seguros."""

    # --- Cortes -----------------------------------------------------------
    max_cuts: int = C.DEFAULT_MAX_CUTS
    min_cut_duration: int = C.DEFAULT_MIN_CUT_SECONDS
    max_cut_duration: int = C.DEFAULT_MAX_CUT_SECONDS
    min_viral_score: int = C.MIN_VIRAL_SCORE

    # --- Conteúdo ---------------------------------------------------------
    # Tipo do vídeo de origem (geral | anime | game | carros): ajusta a
    # análise e a edição para cada categoria de conteúdo.
    video_category: str = C.DEFAULT_VIDEO_CATEGORY
    # Modo de corte da categoria anime:
    #   "ia"    = a IA escolhe os melhores momentos (fala + picos de áudio);
    #   "tempo" = divide o episódio em blocos sequenciais de duração fixa
    #             (ex.: 60 s -> 0:00-0:59, 1:00-1:59, ...).
    anime_cut_mode: str = "ia"
    anime_fixed_seconds: int = 60
    # Enquadramento 9:16 do anime: "blur" (vídeo inteiro sobre fundo
    # desfocado, estilo canais de corte) ou "crop" (central preenchendo).
    anime_framing: str = "blur"

    # --- IA ---------------------------------------------------------------
    language: str = "auto"                       # pt | en | es | auto
    whisper_model: str = C.WHISPER_DEFAULT_MODEL
    ollama_model: str = C.OLLAMA_DEFAULT_MODEL
    ollama_url: str = C.OLLAMA_BASE_URL
    use_gpu: bool = True

    # --- Exportação -------------------------------------------------------
    # "vertical" = reenquadra em 9:16 (Shorts/Reels);
    # "original" = mantém o formato do vídeo de origem (sem crop).
    output_format: str = "vertical"
    resolution_width: int = C.EXPORT_WIDTH
    resolution_height: int = C.EXPORT_HEIGHT
    fps: int = C.EXPORT_FPS
    quality_crf: int = 20                        # 0-51 (menor = melhor)

    # --- Legendas ---------------------------------------------------------
    subtitle_style: str = C.DEFAULT_SUBTITLE_STYLE
    subtitles_enabled: bool = True

    # --- Áudio ------------------------------------------------------------
    audio_normalize: bool = True
    audio_denoise: bool = True
    audio_compress: bool = True

    # --- Limpeza automática ----------------------------------------------
    remove_silences: bool = True
    remove_fillers: bool = True

    # --- Estilo / identidade visual (página Estilo) -----------------------
    watermark_path: str = ""                     # imagem da marca d'água ("" = sem)
    watermark_position: str = "top-right"
    watermark_size: int = 12                     # % da largura do vídeo
    watermark_opacity: int = 70                  # %
    hook_text: str = ""                          # texto fixo no topo ("" = sem)
    show_part_number: bool = True                # "Parte X" nos cortes sequenciais
    progress_bar: bool = False                   # barra de progresso no rodapé
    music_path: str = ""                         # música de fundo ("" = sem)
    music_volume: int = 12                       # %
    original_audio_volume: int = 100             # % (áudio original do vídeo)

    # --- Canal (selo com foto + nome + @, sobreposto nos shorts) ----------
    channel_name: str = ""
    channel_handle: str = ""                     # ex.: @_shimeji_
    channel_avatar_path: str = ""                # foto do canal
    channel_badge_position: str = "bottom"       # top | bottom

    # --- Narração por IA (Piper, local/offline) ----------------------------
    tts_enabled: bool = False
    tts_text: str = ""                           # texto narrado no início do short
    tts_voice: str = C.TTS_DEFAULT_VOICE

    # --- Editor de vídeo completo (aba Editor) -----------------------------
    # Abertura opcional aplicada antes do vídeo original (sem cortar em
    # Shorts): narração por IA e/ou transição de estática de TV.
    editor_narration_enabled: bool = False
    editor_narration_text: str = ""
    editor_narration_voice: str = C.TTS_DEFAULT_VOICE
    editor_static_enabled: bool = True
    editor_static_seconds: int = 2                # 1-8s
    # Música de fundo tocando por baixo da narração (independente da música
    # da página Estilo, usada nos Shorts).
    editor_music_path: str = ""
    editor_music_volume: int = 20                 # %

    # --- Redublagem por IA (aba Redublagem) --------------------------------
    # Troca a voz do narrador de um vídeo já pronto por uma narração de IA,
    # sincronizada por trecho, mantendo (opcionalmente) a música/efeitos de
    # fundo originais via separação por IA (Demucs).
    redub_voice: str = C.TTS_DEFAULT_VOICE
    redub_keep_background: bool = True
    redub_background_volume: int = 70              # % do volume original

    # --- Transcrição (aba Transcrição) --------------------------------------
    # Quando `transcript_auto_export` está ligado, os botões de exportar
    # (TXT/DOCX/MD) gravam direto em `transcript_export_dir` com o nome
    # padrão, sem abrir o diálogo "Salvar como" a cada clique.
    transcript_export_dir: str = ""
    transcript_auto_export: bool = False

    # --- Remover Marca d'Água (aba Remover Marca d'Água) --------------------
    # Guarda o último retângulo marcado (coords do vídeo original) pra
    # pré-preencher no próximo vídeo — útil quando a marca fica sempre no
    # mesmo lugar em todos os vídeos de um canal.
    watermark_region_x: int = -1
    watermark_region_y: int = -1
    watermark_region_w: int = 0
    watermark_region_h: int = 0
    # Como tratar a área marcada: "image"/"text" colam uma imagem/texto por
    # cima depois do delogo (ver `remove_and_cover_watermark`); "blur" só
    # borra a área, sem reconstruir nem colar nada.
    watermark_cover_mode: str = "image"
    watermark_cover_image_path: str = ""
    watermark_cover_text: str = ""

    # --- Modo Humanizado (aba Editar Shorts) --------------------------------
    # Pequenas variações automáticas e sorteadas por renderização (zoom/pan/
    # reenquadramento/cor/nitidez/espelhamento/vinheta/granulado/velocidade)
    # aplicadas junto com a marca d'água, na mesma passada de exportação.
    humanize_enabled: bool = False
    humanize_zoom: bool = True
    humanize_pan: bool = True
    humanize_smart_reframe: bool = True
    humanize_color: bool = True
    humanize_sharpen: bool = True
    humanize_mirror: bool = False
    humanize_vignette: bool = True
    humanize_grain: bool = False
    humanize_speed: bool = True
    humanize_mirror_probability: int = 15   # % de chance de espelhar uma cena aleatória

    # --- Editor Simples (aba Editor Simples, edição sem cortes por IA) ----
    # Marca d'água e narração aplicadas a um vídeo inteiro, sem passar pelo
    # pipeline de análise/corte. Independente do preset da página Estilo e
    # da aba Editor (abertura com narração/estática) acima.
    simple_editor_watermark_path: str = ""
    simple_editor_watermark_position: str = "top-right"
    simple_editor_watermark_size: int = 12              # % da largura do vídeo
    simple_editor_watermark_opacity: int = 70           # %
    simple_editor_music_path: str = ""                  # música de fundo ("" = sem)
    simple_editor_music_volume: int = 20                # %
    simple_editor_narration_enabled: bool = False
    simple_editor_narration_text: str = ""              # texto narrado
    simple_editor_narration_voice: str = C.TTS_DEFAULT_VOICE
    simple_editor_narration_position: str = "start"     # start | custom | end
    simple_editor_narration_time: float = 0.0           # segundos (só quando "custom")

    # --- Interface --------------------------------------------------------
    theme: str = "dark"
    parallel_exports: int = 2

    # --- Efeitos ----------------------------------------------------------
    effects: dict[str, bool] = field(default_factory=lambda: {
        "auto_zoom": True,
        "jump_zoom": True,
        "fade": True,
        "glow": False,
        "highlight": True,
    })

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls) -> "Settings":
        """Carrega config.json; cria com padrões se não existir/estiver corrompido."""
        if C.CONFIG_FILE.exists():
            try:
                raw: dict[str, Any] = json.loads(C.CONFIG_FILE.read_text(encoding="utf-8"))
                valid_keys = {f.name for f in fields(cls)}
                filtered = {k: v for k, v in raw.items() if k in valid_keys}
                settings = cls(**filtered)
                logger.info("Configurações carregadas de %s", C.CONFIG_FILE)
                return settings
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("config.json inválido (%s). Recriando com padrões.", exc)
        settings = cls()
        settings.save()
        return settings

    def save(self) -> None:
        """Persiste as configurações atuais em config.json (UTF-8, identado)."""
        try:
            C.CONFIG_FILE.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("Configurações salvas.")
        except OSError as exc:
            logger.error("Falha ao salvar config.json: %s", exc)
