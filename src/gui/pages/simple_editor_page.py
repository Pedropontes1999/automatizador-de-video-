"""Página Editor Simples: edição simples de um vídeo (marca d'água + narração
de abertura), sem passar pelo pipeline de análise e corte por IA.

O preset aqui é independente do da página Estilo (que vale só para os
Shorts gerados pelo corte) e do da aba Editor (abertura com narração e/ou
transição de estática antes do vídeo original). O vídeo editado sai
inteiro, sem reenquadrar em 9:16, na pasta `output/editados/`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config import constants as C
from src.config.settings import Settings
from src.gui.widgets.drop_area import DropArea
from src.utils.logger import get_logger
from src.utils.paths import sanitize_filename
from src.video.simple_editor import EditOptions, has_edits
from src.workers.simple_editor_worker import SimpleEditorWorker

logger = get_logger("simple_editor_page")


class SimpleEditorPage(QWidget):
    """Formulário + execução da edição simples. Autônoma (não usa fila)."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._source: str | None = None
        self._worker: SimpleEditorWorker | None = None
        self._last_output: str | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save)
        self._build_ui()
        self._load_values()
        self._connect_autosave()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("Editor Simples")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)
        subtitle = QLabel(
            "Aplique marca d'água, música de fundo e/ou uma narração no vídeo "
            "— sem análise de IA e sem cortes. O vídeo sai inteiro, do jeito "
            "que entrou (só com a edição escolhida por cima)."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        self.drop_area = DropArea()
        self.drop_area.fileSelected.connect(self.set_source)
        outer.addWidget(self.drop_area)
        self.source_label = QLabel("Nenhum vídeo selecionado.")
        self.source_label.setObjectName("Muted")
        outer.addWidget(self.source_label)

        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(10)

        # -- Marca d'água --------------------------------------------------- #
        form.addRow(self._section("🖼 Marca d'água"))
        self.watermark_path = QLineEdit()
        self.watermark_path.setReadOnly(True)
        self.watermark_path.setPlaceholderText("Nenhuma imagem escolhida (opcional)")
        form.addRow("Imagem:", self._file_row(self.watermark_path, self._pick_watermark))
        self.watermark_position = QComboBox()
        for slug, label in C.WATERMARK_POSITIONS.items():
            self.watermark_position.addItem(label, userData=slug)
        self.watermark_size = QSpinBox(minimum=5, maximum=40, suffix=" %")
        self.watermark_size.setToolTip("Largura da marca d'água em % da largura do vídeo")
        self.watermark_opacity = QSpinBox(minimum=10, maximum=100, suffix=" %")
        form.addRow("Posição:", self.watermark_position)
        form.addRow("Tamanho:", self.watermark_size)
        form.addRow("Opacidade:", self.watermark_opacity)

        # -- Música de fundo ------------------------------------------------ #
        form.addRow(self._section("🎵 Música de fundo"))
        self.music_path = QLineEdit()
        self.music_path.setReadOnly(True)
        self.music_path.setPlaceholderText("Nenhuma música escolhida (opcional)")
        form.addRow("Arquivo:", self._file_row(self.music_path, self._pick_music))
        self.music_volume = QSpinBox(minimum=0, maximum=100, suffix=" %")
        self.music_volume.setToolTip("Volume da música em relação ao áudio original")
        form.addRow("Volume:", self.music_volume)
        music_hint = QLabel(
            "Toca do início do vídeo em diante. Se a música for mais longa que "
            "o vídeo, ela é cortada junto com ele; se for mais curta, o resto "
            "do vídeo segue sem música."
        )
        music_hint.setObjectName("Muted")
        music_hint.setWordWrap(True)
        form.addRow("", music_hint)

        # -- Narração por IA -------------------------------------------------- #
        form.addRow(self._section("🎙 Narração por IA (offline, ~10-12s por trecho — baixa o modelo na 1ª vez)"))
        self.narration_enabled = QCheckBox("Narrar um texto em algum momento do vídeo")
        self.narration_voice = QComboBox()
        for voice, label in C.TTS_VOICES.items():
            self.narration_voice.addItem(label, userData=voice)
        self.narration_position = QComboBox()
        self.narration_position.addItem("No início do vídeo", userData="start")
        self.narration_position.addItem("Em um momento específico", userData="custom")
        self.narration_position.addItem("No final do vídeo", userData="end")
        self.narration_position.currentIndexChanged.connect(
            self._on_narration_position_changed
        )
        self.narration_time_label = QLabel("Em que segundo:")
        self.narration_time = QDoubleSpinBox(minimum=0, maximum=86400, suffix=" s")
        self.narration_time.setDecimals(1)
        self.narration_time.setToolTip(
            "Segundo exato do vídeo onde a narração entra (ex.: 30 = 00:30)."
        )
        self.narration_text = QPlainTextEdit()
        self.narration_text.setPlaceholderText(
            "Escreva o texto que a IA vai narrar.\n"
            "O vídeo fica parado no frame daquele instante enquanto ela fala."
        )
        self.narration_text.setFixedHeight(90)
        form.addRow("", self.narration_enabled)
        form.addRow("Voz:", self.narration_voice)
        form.addRow("Quando falar:", self.narration_position)
        form.addRow(self.narration_time_label, self.narration_time)
        form.addRow("Texto:", self.narration_text)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # -- Ações ------------------------------------------------------- #
        actions = QHBoxLayout()
        self.apply_button = QPushButton("🎬 Aplicar edição")
        self.apply_button.setObjectName("Primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._start_edit)
        self.open_folder_button = QPushButton("📂 Abrir pasta")
        self.open_folder_button.setVisible(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        actions.addWidget(self.apply_button, stretch=1)
        actions.addWidget(self.open_folder_button)
        outer.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminado: ffmpeg não reporta %
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        self.status_label = QLabel("Pronto.")
        self.status_label.setObjectName("Muted")
        outer.addWidget(self.status_label)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _file_row(self, line_edit: QLineEdit, pick_slot) -> QWidget:
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

    def _connect_autosave(self) -> None:
        def debounced(*_args) -> None:
            self._save_timer.start(500)

        self.watermark_path.textChanged.connect(debounced)
        self.music_path.textChanged.connect(debounced)
        self.narration_text.textChanged.connect(debounced)
        self.watermark_position.currentIndexChanged.connect(lambda _i: self.save())
        self.narration_voice.currentIndexChanged.connect(lambda _i: self.save())
        self.narration_position.currentIndexChanged.connect(lambda _i: self.save())
        self.narration_enabled.toggled.connect(lambda _c: self.save())
        self.watermark_size.valueChanged.connect(debounced)
        self.watermark_opacity.valueChanged.connect(debounced)
        self.music_volume.valueChanged.connect(debounced)
        self.narration_time.valueChanged.connect(debounced)

        # Habilita/desabilita "Aplicar edição" conforme há algo para aplicar.
        self.watermark_path.textChanged.connect(lambda _t: self._refresh_apply_enabled())
        self.music_path.textChanged.connect(lambda _t: self._refresh_apply_enabled())
        self.narration_text.textChanged.connect(lambda: self._refresh_apply_enabled())
        self.narration_enabled.toggled.connect(lambda _c: self._refresh_apply_enabled())

    def _on_narration_position_changed(self, _index: int) -> None:
        """Só mostra o campo de segundo quando a posição é "específica"."""
        is_custom = self.narration_position.currentData() == "custom"
        self.narration_time_label.setVisible(is_custom)
        self.narration_time.setVisible(is_custom)

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
        self.watermark_path.setText(s.simple_editor_watermark_path)
        index = self.watermark_position.findData(s.simple_editor_watermark_position)
        self.watermark_position.setCurrentIndex(max(index, 0))
        self.watermark_size.setValue(s.simple_editor_watermark_size)
        self.watermark_opacity.setValue(s.simple_editor_watermark_opacity)
        self.music_path.setText(s.simple_editor_music_path)
        self.music_volume.setValue(s.simple_editor_music_volume)
        self.narration_enabled.setChecked(s.simple_editor_narration_enabled)
        voice_index = self.narration_voice.findData(s.simple_editor_narration_voice)
        self.narration_voice.setCurrentIndex(max(voice_index, 0))
        position_index = self.narration_position.findData(s.simple_editor_narration_position)
        self.narration_position.setCurrentIndex(max(position_index, 0))
        self.narration_time.setValue(s.simple_editor_narration_time)
        self.narration_text.setPlainText(s.simple_editor_narration_text)
        self._on_narration_position_changed(self.narration_position.currentIndex())

    def save(self) -> None:
        """Grava o preset do editor simples em Settings + config.json."""
        s = self.settings
        s.simple_editor_watermark_path = self.watermark_path.text().strip()
        s.simple_editor_watermark_position = self.watermark_position.currentData()
        s.simple_editor_watermark_size = self.watermark_size.value()
        s.simple_editor_watermark_opacity = self.watermark_opacity.value()
        s.simple_editor_music_path = self.music_path.text().strip()
        s.simple_editor_music_volume = self.music_volume.value()
        s.simple_editor_narration_enabled = self.narration_enabled.isChecked()
        s.simple_editor_narration_voice = self.narration_voice.currentData()
        s.simple_editor_narration_position = self.narration_position.currentData()
        s.simple_editor_narration_time = self.narration_time.value()
        s.simple_editor_narration_text = self.narration_text.toPlainText().strip()
        s.save()
        logger.info("Preset do editor simples salvo.")

    # ------------------------------------------------------------------ #
    def set_source(self, source: str) -> None:
        """Define o vídeo de origem e habilita o botão conforme as opções."""
        self._source = source
        display = source if len(source) < 90 else source[:87] + "..."
        self.source_label.setText(f"🎞 {display}")
        self.open_folder_button.setVisible(False)
        self._refresh_apply_enabled()

    def _current_options(self) -> EditOptions:
        return EditOptions(
            watermark_path=self.watermark_path.text().strip(),
            watermark_position=self.watermark_position.currentData(),
            watermark_size=self.watermark_size.value(),
            watermark_opacity=self.watermark_opacity.value(),
            music_path=self.music_path.text().strip(),
            music_volume=self.music_volume.value(),
            narration_text=(
                self.narration_text.toPlainText().strip()
                if self.narration_enabled.isChecked() else ""
            ),
            narration_voice=self.narration_voice.currentData(),
            narration_position=self.narration_position.currentData(),
            narration_time=self.narration_time.value(),
        )

    def _refresh_apply_enabled(self) -> None:
        ready = self._source is not None and has_edits(self._current_options())
        self.apply_button.setEnabled(ready and not self.is_running())

    def is_running(self) -> bool:
        """Indica se há uma edição em andamento (usado ao fechar a janela)."""
        return self._worker is not None and self._worker.isRunning()

    def wait_running_worker(self, timeout_ms: int) -> bool:
        """Aguarda o worker atual encerrar; True se terminou dentro do prazo."""
        if self._worker is None:
            return True
        return self._worker.wait(timeout_ms)

    def terminate_running_worker(self) -> None:
        """Força o encerramento do worker (último recurso, ao fechar o app)."""
        if self._worker is not None:
            self._worker.terminate()
            self._worker.wait(3000)

    # ------------------------------------------------------------------ #
    def _start_edit(self) -> None:
        if self._source is None:
            return
        options = self._current_options()
        if not has_edits(options):
            QMessageBox.information(
                self, "Nada para aplicar",
                "Escolha uma marca d'água e/ou ative a narração antes de aplicar.",
            )
            return

        output_path = self._build_output_path(self._source)
        self._worker = SimpleEditorWorker(
            self._source, output_path, options, use_gpu=self.settings.use_gpu,
        )
        self._worker.progressChanged.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self.apply_button.setEnabled(False)
        self.open_folder_button.setVisible(False)
        self.progress.setVisible(True)
        self.status_label.setText("Iniciando...")

    @staticmethod
    def _build_output_path(source: str) -> Path:
        C.EDITOR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = sanitize_filename(Path(source).stem)
        return C.EDITOR_OUTPUT_DIR / f"{stem}_editado.mp4"

    def _on_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_succeeded(self, output_path: str) -> None:
        self._last_output = output_path
        self.progress.setVisible(False)
        self.status_label.setText(f"Concluído: {output_path}")
        self.open_folder_button.setVisible(True)
        self._refresh_apply_enabled()
        QMessageBox.information(
            self, "Edição concluída",
            f"Vídeo editado salvo em:\n{output_path}",
        )

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.status_label.setText("Erro na edição.")
        self._refresh_apply_enabled()
        QMessageBox.warning(self, "Erro na edição", message)

    def _open_output_folder(self) -> None:
        if not self._last_output:
            return
        folder = str(Path(self._last_output).parent)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
