"""Modal "Transcrição concluída": visualizar/editar o texto reconhecido pela
IA e exportar em TXT, DOCX, Markdown ou como prompt pronto pra colar num
ChatGPT/Claude (texto limpo ou já com instruções de reescrita de roteiro).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.config.settings import Settings
from src.models.domain import Transcription
from src.services.transcript_export_service import TranscriptExportService
from src.utils.logger import get_logger

logger = get_logger("transcript_dialog")


class TranscriptDialog(QDialog):
    """Janela pós-transcrição: texto editável + ações de exportação."""

    def __init__(
        self, transcription: Transcription, video_title: str, settings: Settings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._video_title = video_title
        self._export = TranscriptExportService()
        self.setWindowTitle("Transcrição concluída")
        self.resize(720, 640)
        self._build_ui()
        self.text_edit.setPlainText(self._export.format_readable(transcription))

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("Transcrição concluída")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Revise e edite o texto abaixo antes de exportar. Quebras de "
            "parágrafo já foram inseridas nas pausas mais longas que 1s da "
            "narração original."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Transcrição...")
        root.addWidget(self.text_edit, stretch=1)

        # -- Pasta de exportação automática -------------------------------- #
        export_row = QHBoxLayout()
        self.auto_export_check = QCheckBox("Exportar automaticamente para:")
        self.auto_export_check.setToolTip(
            "Quando marcado, os botões de exportar gravam direto nesta "
            "pasta (nome de arquivo automático), sem abrir 'Salvar como'."
        )
        self.export_dir_input = QLineEdit()
        self.export_dir_input.setReadOnly(True)
        self.export_dir_input.setPlaceholderText("Nenhuma pasta escolhida")
        choose_dir_button = QPushButton("Escolher pasta...")
        choose_dir_button.clicked.connect(self._pick_export_dir)
        export_row.addWidget(self.auto_export_check)
        export_row.addWidget(self.export_dir_input, stretch=1)
        export_row.addWidget(choose_dir_button)
        root.addLayout(export_row)

        self.auto_export_check.setChecked(self.settings.transcript_auto_export)
        self.export_dir_input.setText(self.settings.transcript_export_dir)
        self.auto_export_check.toggled.connect(self._save_export_prefs)

        # -- Ações ---------------------------------------------------------- #
        actions = QHBoxLayout()
        copy_button = QPushButton("📋 Copiar")
        copy_button.clicked.connect(self._copy_to_clipboard)
        txt_button = QPushButton("💾 Salvar TXT")
        txt_button.clicked.connect(lambda: self._save_as("txt"))
        docx_button = QPushButton("💾 Salvar DOCX")
        docx_button.clicked.connect(lambda: self._save_as("docx"))
        md_button = QPushButton("💾 Salvar MD")
        md_button.clicked.connect(lambda: self._save_as("md"))
        actions.addWidget(copy_button)
        actions.addWidget(txt_button)
        actions.addWidget(docx_button)
        actions.addWidget(md_button)
        root.addLayout(actions)

        ai_actions = QHBoxLayout()
        ai_export_button = QPushButton("🤖 Exportar para IA")
        ai_export_button.setToolTip(
            "Salva um .txt só com a narração limpa (sem timestamps/IDs/"
            "metadados), pronto pra colar num ChatGPT/Claude."
        )
        ai_export_button.clicked.connect(self._export_for_ai)
        script_button = QPushButton("✨ Gerar Roteiro IA")
        script_button.setToolTip(
            "Salva um .txt com instruções de roteirista + a transcrição — "
            "pronto pra colar num ChatGPT/Claude e pedir pra reescrever "
            "sem copiar as frases originais."
        )
        script_button.clicked.connect(self._generate_ai_script)
        ai_actions.addWidget(ai_export_button)
        ai_actions.addWidget(script_button)
        ai_actions.addStretch()
        root.addLayout(ai_actions)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        root.addWidget(self.status_label)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        root.addLayout(close_row)

    # ------------------------------------------------------------------ #
    def _pick_export_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Escolher pasta de exportação", self.export_dir_input.text(),
        )
        if folder:
            self.export_dir_input.setText(folder)
            self.auto_export_check.setChecked(True)
            self._save_export_prefs()

    def _save_export_prefs(self) -> None:
        self.settings.transcript_auto_export = self.auto_export_check.isChecked()
        self.settings.transcript_export_dir = self.export_dir_input.text().strip()
        self.settings.save()

    def _target_path(self, suffix: str, extension: str) -> Path | None:
        """Resolve o caminho de saída: pasta automática (se configurada) ou
        diálogo 'Salvar como'."""
        filename = self._export.default_filename(self._video_title, suffix, extension)
        if self.auto_export_check.isChecked() and self.export_dir_input.text().strip():
            folder = Path(self.export_dir_input.text().strip())
            folder.mkdir(parents=True, exist_ok=True)
            return folder / filename
        exts = {"txt": "Texto (*.txt)", "docx": "Word (*.docx)", "md": "Markdown (*.md)"}
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar transcrição", filename, exts.get(extension, "Todos (*)"),
        )
        return Path(path) if path else None

    # ------------------------------------------------------------------ #
    def _copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self.text_edit.toPlainText())
        self.status_label.setText("✔ Texto copiado para a área de transferência.")

    def _save_as(self, extension: str) -> None:
        text = self.text_edit.toPlainText()
        path = self._target_path("Transcricao", extension)
        if path is None:
            return
        try:
            if extension == "txt":
                self._export.save_txt(text, path)
            elif extension == "md":
                self._export.save_markdown(text, path, self._video_title)
            else:
                self._export.save_docx(text, path, self._video_title)
        except RuntimeError as exc:
            QMessageBox.warning(self, "Erro ao exportar", str(exc))
            return
        self.status_label.setText(f"✔ Salvo em {path}")

    def _export_for_ai(self) -> None:
        text = self.text_edit.toPlainText()
        path = self._target_path("para_ia", "txt")
        if path is None:
            return
        self._export.save_txt(text.strip() + "\n", path)
        self.status_label.setText(f"✔ Exportado para IA: {path}")

    def _generate_ai_script(self) -> None:
        text = self.text_edit.toPlainText()
        path = self._target_path("roteiro_para_ia", "txt")
        if path is None:
            return
        self._export.save_txt(self._export.build_script_prompt(text), path)
        self.status_label.setText(f"✔ Prompt de roteiro gerado: {path}")
