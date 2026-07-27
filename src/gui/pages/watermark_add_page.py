"""Página Marca d'Água: cola uma imagem ou um texto por cima de um vídeo
inteiro, na posição escolhida — sem cortes nem passagem pelo pipeline de
análise por IA.

O oposto da aba "Editar Shorts" (que remove/cobre uma marca já existente).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.config import constants as C
from src.config.settings import Settings
from src.gui.widgets.drop_area import DropArea
from src.utils.logger import get_logger
from src.utils.paths import sanitize_filename
from src.video.watermark_adder import WatermarkAddOptions
from src.workers.watermark_adder_worker import WatermarkAdderWorker

logger = get_logger("watermark_add_page")

_MODES = ("image", "text")


class WatermarkAddPage(QWidget):
    """Formulário + execução da marca d'água (imagem ou texto). Autônoma."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._source: str | None = None
        self._worker: WatermarkAdderWorker | None = None
        self._last_output: str | None = None
        self._build_ui()
        self._load_values()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("Marca d'água")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)
        subtitle = QLabel(
            "Envie um vídeo, escolha uma imagem (ex.: logo do seu canal) ou "
            "digite um texto, e escolha onde ela aparece. O vídeo sai inteiro, "
            "do jeito que entrou, só com a marca d'água por cima."
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
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        content_layout.addWidget(self._section("🖼 Tipo de marca d'água"))
        mode_row = QHBoxLayout()
        self.mode_image = QRadioButton("🖼 Imagem")
        self.mode_text = QRadioButton("🔤 Texto")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_image, 0)
        self.mode_group.addButton(self.mode_text, 1)
        self.mode_image.setChecked(True)
        self.mode_group.idClicked.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_image)
        mode_row.addWidget(self.mode_text)
        mode_row.addStretch()
        content_layout.addLayout(mode_row)

        self.mode_stack = QStackedWidget()

        image_page = QWidget()
        image_form = QFormLayout(image_page)
        image_form.setContentsMargins(0, 0, 0, 0)
        self.image_path = QLineEdit()
        self.image_path.setReadOnly(True)
        self.image_path.setPlaceholderText(
            "Imagem da marca d'água (ex.: logo do seu canal; pode ter fundo transparente)"
        )
        image_form.addRow("Imagem:", self._file_row(self.image_path, self._pick_image))
        self.image_size = QSpinBox(minimum=5, maximum=40, suffix=" %")
        self.image_size.setToolTip("Largura da marca d'água em % da largura do vídeo")
        image_form.addRow("Tamanho:", self.image_size)
        self.mode_stack.addWidget(image_page)

        text_page = QWidget()
        text_form = QFormLayout(text_page)
        text_form.setContentsMargins(0, 0, 0, 0)
        self.text_value = QLineEdit()
        self.text_value.setPlaceholderText(
            "Texto da marca d'água (ex.: o nome ou @ do seu canal)"
        )
        text_form.addRow("Texto:", self.text_value)
        self.text_font_size = QSpinBox(minimum=12, maximum=200, suffix=" px")
        text_form.addRow("Tamanho da fonte:", self.text_font_size)
        self.mode_stack.addWidget(text_page)

        content_layout.addWidget(self.mode_stack)

        content_layout.addWidget(self._section("📍 Posição e opacidade"))
        common_form = QFormLayout()
        self.position = QComboBox()
        for slug, label in C.ADD_WATERMARK_POSITIONS.items():
            self.position.addItem(label, userData=slug)
        common_form.addRow("Posição:", self.position)
        self.opacity = QSpinBox(minimum=10, maximum=100, suffix=" %")
        common_form.addRow("Opacidade:", self.opacity)
        content_layout.addLayout(common_form)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # -- Ações ------------------------------------------------------- #
        actions = QHBoxLayout()
        self.process_button = QPushButton("💧 Aplicar marca d'água")
        self.process_button.setObjectName("Primary")
        self.process_button.setEnabled(False)
        self.process_button.clicked.connect(self._process)
        self.open_folder_button = QPushButton("📂 Abrir pasta")
        self.open_folder_button.setVisible(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        actions.addWidget(self.process_button, stretch=1)
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

        self._connect_autosave()

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
        self.image_path.textChanged.connect(lambda _t: self.save())
        self.image_size.valueChanged.connect(lambda _v: self.save())
        self.text_value.textChanged.connect(lambda _t: self.save())
        self.text_font_size.valueChanged.connect(lambda _v: self.save())
        self.position.currentIndexChanged.connect(lambda _i: self.save())
        self.opacity.valueChanged.connect(lambda _v: self.save())

        self.image_path.textChanged.connect(lambda _t: self._refresh_process_enabled())
        self.text_value.textChanged.connect(lambda _t: self._refresh_process_enabled())

    def _on_mode_changed(self, mode_id: int) -> None:
        self.mode_stack.setCurrentIndex(mode_id)
        self._refresh_process_enabled()
        self.save()

    def _mode(self) -> str:
        return _MODES[self.mode_group.checkedId()]

    def _pick_image(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in C.SUPPORTED_IMAGE_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher imagem da marca d'água", "", f"Imagens ({patterns})",
        )
        if path:
            self.image_path.setText(path)

    # ------------------------------------------------------------------ #
    def _load_values(self) -> None:
        s = self.settings
        self.image_path.setText(s.add_watermark_image_path)
        self.image_size.setValue(s.add_watermark_size)
        self.text_value.setText(s.add_watermark_text)
        self.text_font_size.setValue(s.add_watermark_font_size)
        self.opacity.setValue(s.add_watermark_opacity)
        index = self.position.findData(s.add_watermark_position)
        self.position.setCurrentIndex(max(index, 0))

        mode_index = _MODES.index(s.add_watermark_mode) if s.add_watermark_mode in _MODES else 0
        self.mode_group.button(mode_index).setChecked(True)
        self.mode_stack.setCurrentIndex(mode_index)

    def save(self) -> None:
        """Grava o preset da marca d'água em Settings + config.json."""
        s = self.settings
        s.add_watermark_mode = self._mode()
        s.add_watermark_image_path = self.image_path.text().strip()
        s.add_watermark_size = self.image_size.value()
        s.add_watermark_text = self.text_value.text().strip()
        s.add_watermark_font_size = self.text_font_size.value()
        s.add_watermark_position = self.position.currentData()
        s.add_watermark_opacity = self.opacity.value()
        s.save()
        logger.debug("Preset da marca d'água salvo.")

    # ------------------------------------------------------------------ #
    def set_source(self, source: str) -> None:
        """Define o vídeo de origem e habilita o botão conforme as opções."""
        self._source = source
        display = source if len(source) < 90 else source[:87] + "..."
        self.source_label.setText(f"🎞 {display}")
        self.open_folder_button.setVisible(False)
        self.status_label.setText("Pronto.")
        self._refresh_process_enabled()

    def _current_options(self) -> WatermarkAddOptions:
        return WatermarkAddOptions(
            mode=self._mode(),
            image_path=self.image_path.text().strip(),
            text=self.text_value.text().strip(),
            font_size=self.text_font_size.value(),
            position=self.position.currentData(),
            size=self.image_size.value(),
            opacity=self.opacity.value(),
        )

    def _refresh_process_enabled(self) -> None:
        mode = self._mode()
        has_content = (
            bool(self.image_path.text().strip()) if mode == "image"
            else bool(self.text_value.text().strip())
        )
        ready = self._source is not None and has_content and not self.is_running()
        self.process_button.setEnabled(ready)

    # ------------------------------------------------------------------ #
    # Processamento
    # ------------------------------------------------------------------ #
    def is_running(self) -> bool:
        """Indica se há uma exportação em andamento (usado ao fechar a janela)."""
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

    def _process(self) -> None:
        if self._source is None:
            return
        self.save()
        options = self._current_options()

        output_path = self._build_output_path(self._source)
        self._worker = WatermarkAdderWorker(
            self._source, output_path, options, use_gpu=self.settings.use_gpu,
        )
        self._worker.progressChanged.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self.process_button.setEnabled(False)
        self.open_folder_button.setVisible(False)
        self.progress.setVisible(True)
        self.status_label.setText("Iniciando...")

    @staticmethod
    def _build_output_path(source: str) -> Path:
        C.WATERMARK_ADD_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = sanitize_filename(Path(source).stem)
        return C.WATERMARK_ADD_OUTPUT_DIR / f"{stem}_com_marca.mp4"

    def _on_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_succeeded(self, output_path: str) -> None:
        self._last_output = output_path
        self.progress.setVisible(False)
        self.status_label.setText(f"Concluído: {output_path}")
        self.open_folder_button.setVisible(True)
        self._refresh_process_enabled()
        QMessageBox.information(
            self, "Marca d'água aplicada", f"Vídeo salvo em:\n{output_path}",
        )

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.status_label.setText("Erro ao aplicar marca d'água.")
        self._refresh_process_enabled()
        QMessageBox.warning(self, "Erro ao aplicar marca d'água", message)

    def _open_output_folder(self) -> None:
        if not self._last_output:
            return
        folder = str(Path(self._last_output).parent)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
