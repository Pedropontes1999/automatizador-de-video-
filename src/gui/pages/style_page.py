"""Página Estilo: identidade visual dos Shorts e narração por IA.

Aqui o usuário define o "preset" aplicado automaticamente a todo corte
exportado: marca d'água, texto de gancho, "Parte X", barra de progresso,
música de fundo e narração (vozes Microsoft via edge-tts).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config import constants as C
from src.config.settings import Settings
from src.utils.logger import get_logger

logger = get_logger("style_page")


class StylePage(QWidget):
    """Formulário do preset de estilo, salvo em config.json."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._build_ui()
        self._load_values()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Estilo dos Shorts")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)
        subtitle = QLabel(
            "Tudo aqui é aplicado automaticamente em todos os cortes exportados. "
            "Deixe em branco o que ainda não quiser usar."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(10)

        # -- Marca d'água ------------------------------------------------- #
        form.addRow(self._section("🖼 Marca d'água"))
        self.watermark_path = QLineEdit()
        self.watermark_path.setReadOnly(True)
        self.watermark_path.setPlaceholderText("Nenhuma imagem escolhida (opcional)")
        form.addRow("Imagem:", self._file_row(
            self.watermark_path, self._pick_watermark,
        ))
        self.watermark_position = QComboBox()
        for slug, label in C.WATERMARK_POSITIONS.items():
            self.watermark_position.addItem(label, userData=slug)
        self.watermark_size = QSpinBox(minimum=5, maximum=40, suffix=" %")
        self.watermark_size.setToolTip("Largura da marca d'água em % da largura do vídeo")
        self.watermark_opacity = QSpinBox(minimum=10, maximum=100, suffix=" %")
        form.addRow("Posição:", self.watermark_position)
        form.addRow("Tamanho:", self.watermark_size)
        form.addRow("Opacidade:", self.watermark_opacity)

        # -- Textos no vídeo ----------------------------------------------- #
        form.addRow(self._section("📝 Textos no vídeo"))
        self.hook_text = QLineEdit()
        self.hook_text.setPlaceholderText(
            "Ex.: O MELHOR MOMENTO DO EPISÓDIO 🔥 (fica fixo no topo; opcional)"
        )
        self.show_part_number = QCheckBox(
            'Mostrar "Parte X" nos cortes sequenciais (modo tempo fixo)'
        )
        form.addRow("Título/gancho:", self.hook_text)
        form.addRow("", self.show_part_number)

        # -- Barra de progresso -------------------------------------------- #
        form.addRow(self._section("📊 Barra de progresso"))
        self.progress_bar = QCheckBox(
            "Mostrar barra de progresso no rodapé do vídeo"
        )
        form.addRow("", self.progress_bar)

        # -- Música de fundo ------------------------------------------------ #
        form.addRow(self._section("🎵 Música de fundo"))
        self.music_path = QLineEdit()
        self.music_path.setReadOnly(True)
        self.music_path.setPlaceholderText("Nenhuma música escolhida (opcional)")
        form.addRow("Arquivo:", self._file_row(self.music_path, self._pick_music))
        self.music_volume = QSpinBox(minimum=0, maximum=100, suffix=" %")
        self.music_volume.setToolTip("Volume da música em relação ao áudio original")
        form.addRow("Volume:", self.music_volume)

        # -- Narração por IA ------------------------------------------------ #
        form.addRow(self._section("🎙 Narração por IA (vozes Microsoft — precisa de internet)"))
        self.tts_enabled = QCheckBox("Narrar um texto no início de cada short")
        self.tts_voice = QComboBox()
        for voice, label in C.TTS_VOICES.items():
            self.tts_voice.addItem(label, userData=voice)
        self.tts_text = QPlainTextEdit()
        self.tts_text.setPlaceholderText(
            "Escreva o texto que a IA vai narrar no começo de cada corte.\n"
            "Ex.: Se você gosta de anime, segue o canal pra não perder a parte 2!"
        )
        self.tts_text.setFixedHeight(90)
        form.addRow("", self.tts_enabled)
        form.addRow("Voz:", self.tts_voice)
        form.addRow("Texto:", self.tts_text)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()
        save = QPushButton("💾 Salvar estilo")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        footer.addWidget(save)
        outer.addLayout(footer)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _file_row(self, line_edit: QLineEdit, pick_slot) -> QWidget:
        """Linha com campo somente leitura + botões Escolher/Remover."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        choose = QPushButton("📂 Escolher...")
        choose.clicked.connect(pick_slot)
        clear = QPushButton("✖")
        clear.setToolTip("Remover")
        clear.setFixedWidth(36)
        clear.clicked.connect(lambda: line_edit.setText(""))
        layout.addWidget(line_edit, stretch=1)
        layout.addWidget(choose)
        layout.addWidget(clear)
        return row

    # ------------------------------------------------------------------ #
    def _pick_watermark(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in C.SUPPORTED_IMAGE_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher marca d'água", "", f"Imagens ({patterns})",
        )
        if path:
            self.watermark_path.setText(path)

    def _pick_music(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in C.SUPPORTED_AUDIO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher música de fundo", "", f"Áudios ({patterns})",
        )
        if path:
            self.music_path.setText(path)

    # ------------------------------------------------------------------ #
    def _load_values(self) -> None:
        s = self.settings
        self.watermark_path.setText(s.watermark_path)
        index = self.watermark_position.findData(s.watermark_position)
        self.watermark_position.setCurrentIndex(max(index, 0))
        self.watermark_size.setValue(s.watermark_size)
        self.watermark_opacity.setValue(s.watermark_opacity)
        self.hook_text.setText(s.hook_text)
        self.show_part_number.setChecked(s.show_part_number)
        self.progress_bar.setChecked(s.progress_bar)
        self.music_path.setText(s.music_path)
        self.music_volume.setValue(s.music_volume)
        self.tts_enabled.setChecked(s.tts_enabled)
        voice_index = self.tts_voice.findData(s.tts_voice)
        self.tts_voice.setCurrentIndex(max(voice_index, 0))
        self.tts_text.setPlainText(s.tts_text)

    def save(self) -> None:
        """Grava o preset em Settings + config.json."""
        s = self.settings
        s.watermark_path = self.watermark_path.text().strip()
        s.watermark_position = self.watermark_position.currentData()
        s.watermark_size = self.watermark_size.value()
        s.watermark_opacity = self.watermark_opacity.value()
        s.hook_text = self.hook_text.text().strip()
        s.show_part_number = self.show_part_number.isChecked()
        s.progress_bar = self.progress_bar.isChecked()
        s.music_path = self.music_path.text().strip()
        s.music_volume = self.music_volume.value()
        s.tts_enabled = self.tts_enabled.isChecked()
        s.tts_voice = self.tts_voice.currentData()
        s.tts_text = self.tts_text.toPlainText().strip()
        s.save()
        logger.info("Estilo salvo.")
