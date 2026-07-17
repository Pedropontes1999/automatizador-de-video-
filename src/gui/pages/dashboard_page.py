"""Dashboard: uso de CPU/GPU/RAM em tempo real, estatísticas de cortes e
tempo economizado.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from src.database.repository import ProjectRepository
from src.utils.logger import get_logger
from src.utils.system_monitor import get_stats

logger = get_logger("dashboard")

# Estimativa: cada corte manual levaria ~20 min de edição.
MINUTES_SAVED_PER_CUT = 20


class _StatCard(QWidget):
    """Card simples com título e valor grande."""

    def __init__(self, title: str, initial: str = "-") -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        label = QLabel(title)
        label.setObjectName("CardMuted")
        self.value = QLabel(initial)
        self.value.setObjectName("SectionTitle")
        layout.addWidget(label)
        layout.addWidget(self.value)


class _UsageBar(QWidget):
    """Barra de uso de recurso (CPU/RAM/GPU) com rótulo."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.label = QLabel(title)
        self.label.setObjectName("CardMuted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)

    def update_value(self, percent: float | None, text: str | None = None) -> None:
        """Atualiza a barra; percent None mostra 'indisponível'."""
        if percent is None:
            self.bar.setValue(0)
            self.bar.setFormat("indisponível")
        else:
            self.bar.setValue(int(percent))
            self.bar.setFormat(text or f"{percent:.0f}%")


class DashboardPage(QWidget):
    """Página de monitoramento e estatísticas."""

    REFRESH_MS = 1500

    def __init__(self) -> None:
        super().__init__()
        self._current_status = "Ocioso"
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Dashboard")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        # -- Recursos do sistema ---------------------------------------- #
        usage_row = QHBoxLayout()
        self.cpu_bar = _UsageBar("🖥 CPU")
        self.ram_bar = _UsageBar("🧠 RAM")
        self.gpu_bar = _UsageBar("🎮 GPU")
        usage_row.addWidget(self.cpu_bar)
        usage_row.addWidget(self.ram_bar)
        usage_row.addWidget(self.gpu_bar)
        root.addLayout(usage_row)

        # -- Estatísticas ------------------------------------------------- #
        grid = QGridLayout()
        grid.setSpacing(14)
        self.projects_card = _StatCard("Projetos processados")
        self.cuts_card = _StatCard("Cortes gerados")
        self.saved_card = _StatCard("Tempo economizado")
        self.status_card = _StatCard("Status atual", "Ocioso")
        grid.addWidget(self.projects_card, 0, 0)
        grid.addWidget(self.cuts_card, 0, 1)
        grid.addWidget(self.saved_card, 1, 0)
        grid.addWidget(self.status_card, 1, 1)
        root.addLayout(grid)
        root.addStretch()

        # Timer de atualização (roda na main thread, coleta é leve).
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(self.REFRESH_MS)
        self.refresh_stats()

    # ------------------------------------------------------------------ #
    def set_status(self, text: str) -> None:
        """Atualiza o card de status atual (chamado pela MainWindow)."""
        self._current_status = text
        self.status_card.value.setText(text)

    def refresh_stats(self) -> None:
        """Recalcula estatísticas do banco (projetos, cortes, tempo salvo)."""
        try:
            projects = ProjectRepository.list_all()
            total_cuts = sum(
                len(ProjectRepository.get_cuts(p.id)) for p in projects if p.id
            )
            saved_min = total_cuts * MINUTES_SAVED_PER_CUT
            self.projects_card.value.setText(str(len(projects)))
            self.cuts_card.value.setText(str(total_cuts))
            self.saved_card.value.setText(f"{saved_min // 60}h {saved_min % 60}min")
        except Exception as exc:  # noqa: BLE001 - dashboard nunca quebra a app
            logger.debug("Falha ao atualizar estatísticas: %s", exc)

    def _refresh(self) -> None:
        """Atualiza as barras de uso de recursos."""
        stats = get_stats()
        self.cpu_bar.update_value(stats.cpu_percent)
        self.ram_bar.update_value(
            stats.ram_percent,
            f"{stats.ram_used_gb:.1f} / {stats.ram_total_gb:.1f} GB",
        )
        self.gpu_bar.update_value(stats.gpu_percent)
