"""Histórico de projetos processados (lido do SQLite)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.database.repository import ProjectRepository
from src.utils.logger import get_logger

logger = get_logger("history")


class HistoryPage(QWidget):
    """Tabela com todos os projetos já processados."""

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Histórico de projetos")
        title.setObjectName("SectionTitle")
        refresh = QPushButton("🔄 Atualizar")
        refresh.clicked.connect(self.reload)
        delete = QPushButton("🗑 Excluir selecionado")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete_selected)
        header.addWidget(title, stretch=1)
        header.addWidget(refresh)
        header.addWidget(delete)
        root.addLayout(header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Título", "Duração", "Status", "Data"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self.table, stretch=1)
        self.reload()

    # ------------------------------------------------------------------ #
    def reload(self) -> None:
        """Recarrega a tabela a partir do banco."""
        try:
            projects = ProjectRepository.list_all()
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao carregar histórico: %s", exc)
            return
        self.table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            duration = f"{int(project.duration // 60)}min {int(project.duration % 60)}s"
            for col, value in enumerate(
                (str(project.id), project.title, duration,
                 project.status, project.created_at)
            ):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

    def _delete_selected(self) -> None:
        """Exclui o projeto selecionado na tabela."""
        row = self.table.currentRow()
        if row < 0:
            return
        project_id = int(self.table.item(row, 0).text())
        ProjectRepository.delete(project_id)
        self.reload()
