"""Página de configurações: cortes, IA, legendas, exportação, áudio e tema.

Todos os campos são vinculados ao objeto `Settings` e salvos em config.json
(Ctrl+S ou botão Salvar).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.ai.ollama_client import OllamaClient
from src.config import constants as C
from src.config.settings import Settings
from src.subtitle.styles import STYLES
from src.utils.logger import get_logger

logger = get_logger("settings_page")


class SettingsPage(QWidget):
    """Formulário completo de configurações da aplicação."""

    themeChanged = Signal(str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._build_ui()
        self._load_values()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """Monta o formulário em seções."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Configurações")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)

        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(10)

        # -- Cortes ------------------------------------------------------ #
        form.addRow(self._section("✂ Cortes"))
        self.max_cuts = QSpinBox(minimum=1, maximum=50)
        self.min_duration = QSpinBox(minimum=5, maximum=300, suffix=" s")
        self.max_duration = QSpinBox(minimum=10, maximum=600, suffix=" s")
        self.min_score = QSpinBox(minimum=0, maximum=100)
        form.addRow("Quantidade máxima de cortes:", self.max_cuts)
        form.addRow("Duração mínima:", self.min_duration)
        form.addRow("Duração máxima:", self.max_duration)
        form.addRow("Nota viral mínima (0-100):", self.min_score)

        # -- IA ----------------------------------------------------------- #
        form.addRow(self._section("🤖 Inteligência Artificial"))
        self.language = QComboBox()
        for code, name in C.SUPPORTED_LANGUAGES.items():
            self.language.addItem(name, userData=code)
        self.whisper_model = QComboBox()
        self.whisper_model.addItems(C.WHISPER_MODELS)
        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)
        refresh_models = QPushButton("🔄 Detectar modelos do Ollama")
        refresh_models.clicked.connect(self._refresh_ollama_models)
        self.use_gpu = QCheckBox("Usar GPU quando disponível")
        form.addRow("Idioma:", self.language)
        form.addRow("Modelo Whisper:", self.whisper_model)
        form.addRow("Modelo Ollama:", self.ollama_model)
        form.addRow("", refresh_models)
        form.addRow("", self.use_gpu)

        # -- ElevenLabs (narração em nuvem) --------------------------------- #
        form.addRow(self._section("🎙 ElevenLabs (narração em nuvem, plano pago)"))
        key_row = QHBoxLayout()
        self.elevenlabs_api_key = QLineEdit()
        self.elevenlabs_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.elevenlabs_api_key.setPlaceholderText("Chave de API (elevenlabs.io/app/settings/api-keys)")
        self.show_api_key = QPushButton("👁")
        self.show_api_key.setCheckable(True)
        self.show_api_key.setFixedWidth(32)
        self.show_api_key.toggled.connect(
            lambda show: self.elevenlabs_api_key.setEchoMode(
                QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
            )
        )
        key_row.addWidget(self.elevenlabs_api_key, stretch=1)
        key_row.addWidget(self.show_api_key)
        form.addRow("Chave de API:", key_row)
        eleven_hint = QLabel(
            "Use vozes \"eleven:...\" na Redublagem/Editor (botão \"Detectar "
            "vozes\") depois de colar a chave aqui e salvar."
        )
        eleven_hint.setObjectName("Muted")
        eleven_hint.setWordWrap(True)
        form.addRow("", eleven_hint)

        # -- Chatterbox (narração local, grátis) --------------------------- #
        form.addRow(self._section("🗣 Chatterbox (narração local, grátis)"))
        ref_row = QHBoxLayout()
        self.chatterbox_reference_path = QLineEdit()
        self.chatterbox_reference_path.setReadOnly(True)
        self.chatterbox_reference_path.setPlaceholderText(
            "Nenhum áudio de referência escolhido (usa a voz padrão do Chatterbox)"
        )
        choose_ref = QPushButton("📂 Escolher...")
        choose_ref.clicked.connect(self._pick_chatterbox_reference)
        clear_ref = QPushButton("✖")
        clear_ref.setToolTip("Remover")
        clear_ref.setFixedWidth(36)
        clear_ref.clicked.connect(lambda: self.chatterbox_reference_path.setText(""))
        ref_row.addWidget(self.chatterbox_reference_path, stretch=1)
        ref_row.addWidget(choose_ref)
        ref_row.addWidget(clear_ref)
        form.addRow("Áudio de referência:", ref_row)
        chatterbox_hint = QLabel(
            "Roda no seu computador, sem chave de API. Escolha um clipe curto "
            "(5-15s, fala limpa, sem música/ruído) pra usar a voz \"Personalizada "
            "(Chatterbox)\" na Redublagem/Editor — sem escolher nada, essa opção "
            "usa a voz embutida padrão do modelo."
        )
        chatterbox_hint.setObjectName("Muted")
        chatterbox_hint.setWordWrap(True)
        form.addRow("", chatterbox_hint)

        # -- Legendas ----------------------------------------------------- #
        form.addRow(self._section("💬 Legendas"))
        self.subtitles_enabled = QCheckBox("Gerar legendas automaticamente")
        self.subtitle_style = QComboBox()
        self.subtitle_style.addItems(list(STYLES.keys()))
        form.addRow("", self.subtitles_enabled)
        form.addRow("Estilo:", self.subtitle_style)

        # -- Exportação ---------------------------------------------------- #
        form.addRow(self._section("📤 Exportação"))
        self.output_format = QComboBox()
        self.output_format.addItem("9:16 vertical (Shorts/Reels)", userData="vertical")
        self.output_format.addItem("Original do vídeo (sem reenquadrar)", userData="original")
        form.addRow("Formato de saída:", self.output_format)
        self.fps = QSpinBox(minimum=24, maximum=60)
        self.quality = QSpinBox(minimum=15, maximum=30)
        self.quality.setToolTip("CRF do H264: menor = melhor qualidade")
        self.parallel = QSpinBox(minimum=1, maximum=8)
        form.addRow("FPS:", self.fps)
        form.addRow("Qualidade (CRF):", self.quality)
        form.addRow("Exportações em paralelo:", self.parallel)

        # -- Áudio / limpeza ---------------------------------------------- #
        form.addRow(self._section("🔊 Áudio e limpeza automática"))
        self.audio_normalize = QCheckBox("Normalizar volume (-14 LUFS)")
        self.audio_denoise = QCheckBox("Remover ruído")
        self.audio_compress = QCheckBox("Compressão + limiter")
        self.remove_silences = QCheckBox("Remover silêncios e pausas")
        self.remove_fillers = QCheckBox("Remover vícios de fala (ãh, éh...)")
        for cb in (self.audio_normalize, self.audio_denoise, self.audio_compress,
                   self.remove_silences, self.remove_fillers):
            form.addRow("", cb)

        # -- Efeitos ------------------------------------------------------- #
        form.addRow(self._section("✨ Efeitos"))
        self.fx_auto_zoom = QCheckBox("Zoom automático lento")
        self.fx_jump_zoom = QCheckBox("Jump zoom (punch-in)")
        self.fx_fade = QCheckBox("Fade in/out")
        self.fx_glow = QCheckBox("Glow")
        for cb in (self.fx_auto_zoom, self.fx_jump_zoom, self.fx_fade, self.fx_glow):
            form.addRow("", cb)

        # -- Tema ----------------------------------------------------------- #
        form.addRow(self._section("🎨 Aparência"))
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        form.addRow("Tema:", self.theme)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # -- Salvar ---------------------------------------------------------- #
        footer = QHBoxLayout()
        footer.addStretch()
        save = QPushButton("💾 Salvar  (Ctrl+S)")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        footer.addWidget(save)
        outer.addLayout(footer)

    @staticmethod
    def _section(text: str) -> QLabel:
        """Rótulo de seção do formulário."""
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _pick_chatterbox_reference(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in C.SUPPORTED_AUDIO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher áudio de referência", "", f"Áudios/Vídeos ({patterns})",
        )
        if path:
            self.chatterbox_reference_path.setText(path)

    # ------------------------------------------------------------------ #
    def _load_values(self) -> None:
        """Preenche o formulário com os valores atuais de Settings."""
        s = self.settings
        self.max_cuts.setValue(s.max_cuts)
        self.min_duration.setValue(s.min_cut_duration)
        self.max_duration.setValue(s.max_cut_duration)
        self.min_score.setValue(s.min_viral_score)
        index = self.language.findData(s.language)
        self.language.setCurrentIndex(max(index, 0))
        self.whisper_model.setCurrentText(s.whisper_model)
        self.ollama_model.addItems(list(C.OLLAMA_SUGGESTED_MODELS))
        self.ollama_model.setCurrentText(s.ollama_model)
        self.use_gpu.setChecked(s.use_gpu)
        self.elevenlabs_api_key.setText(s.elevenlabs_api_key)
        self.chatterbox_reference_path.setText(s.chatterbox_reference_path)
        self.subtitles_enabled.setChecked(s.subtitles_enabled)
        self.subtitle_style.setCurrentText(s.subtitle_style)
        fmt_index = self.output_format.findData(s.output_format)
        self.output_format.setCurrentIndex(max(fmt_index, 0))
        self.fps.setValue(s.fps)
        self.quality.setValue(s.quality_crf)
        self.parallel.setValue(s.parallel_exports)
        self.audio_normalize.setChecked(s.audio_normalize)
        self.audio_denoise.setChecked(s.audio_denoise)
        self.audio_compress.setChecked(s.audio_compress)
        self.remove_silences.setChecked(s.remove_silences)
        self.remove_fillers.setChecked(s.remove_fillers)
        self.fx_auto_zoom.setChecked(s.effects.get("auto_zoom", True))
        self.fx_jump_zoom.setChecked(s.effects.get("jump_zoom", True))
        self.fx_fade.setChecked(s.effects.get("fade", True))
        self.fx_glow.setChecked(s.effects.get("glow", False))
        self.theme.setCurrentText(s.theme)

    def save(self) -> None:
        """Grava o formulário em Settings + config.json e aplica o tema."""
        s = self.settings
        s.max_cuts = self.max_cuts.value()
        s.min_cut_duration = self.min_duration.value()
        s.max_cut_duration = self.max_duration.value()
        s.min_viral_score = self.min_score.value()
        s.language = self.language.currentData()
        s.whisper_model = self.whisper_model.currentText()
        s.ollama_model = self.ollama_model.currentText().strip()
        s.use_gpu = self.use_gpu.isChecked()
        s.elevenlabs_api_key = self.elevenlabs_api_key.text().strip()
        s.chatterbox_reference_path = self.chatterbox_reference_path.text().strip()
        s.subtitles_enabled = self.subtitles_enabled.isChecked()
        s.subtitle_style = self.subtitle_style.currentText()
        s.output_format = self.output_format.currentData()
        s.fps = self.fps.value()
        s.quality_crf = self.quality.value()
        s.parallel_exports = self.parallel.value()
        s.audio_normalize = self.audio_normalize.isChecked()
        s.audio_denoise = self.audio_denoise.isChecked()
        s.audio_compress = self.audio_compress.isChecked()
        s.remove_silences = self.remove_silences.isChecked()
        s.remove_fillers = self.remove_fillers.isChecked()
        s.effects.update({
            "auto_zoom": self.fx_auto_zoom.isChecked(),
            "jump_zoom": self.fx_jump_zoom.isChecked(),
            "fade": self.fx_fade.isChecked(),
            "glow": self.fx_glow.isChecked(),
        })
        theme_changed = s.theme != self.theme.currentText()
        s.theme = self.theme.currentText()
        s.save()
        logger.info("Configurações salvas.")
        if theme_changed:
            self.themeChanged.emit(s.theme)

    def _refresh_ollama_models(self) -> None:
        """Consulta o Ollama local e preenche a lista de modelos instalados."""
        models = OllamaClient(self.settings.ollama_url).list_models()
        if models:
            current = self.ollama_model.currentText()
            self.ollama_model.clear()
            self.ollama_model.addItems(models)
            if current in models:
                self.ollama_model.setCurrentText(current)
            logger.info("Modelos do Ollama detectados: %s", ", ".join(models))
        else:
            logger.warning("Ollama offline ou sem modelos instalados.")
