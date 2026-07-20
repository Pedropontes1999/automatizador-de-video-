"""Página principal: entrada de vídeo, botão ANALISAR, progresso,
controles (pausar/retomar/cancelar), cards de cortes e logs em tempo real.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.config.constants import DEFAULT_VIDEO_CATEGORY, VIDEO_CATEGORIES
from src.gui.widgets.cut_card import CutCard
from src.gui.widgets.drop_area import DropArea
from src.gui.widgets.log_panel import LogPanel
from src.models.domain import CutCandidate
from src.video.downloader import is_youtube_url


class HomePage(QWidget):
    """Tela inicial com o fluxo completo de análise."""

    analyzeRequested = Signal(str)   # caminho do arquivo ou URL
    categoryChanged = Signal(str)    # slug do tipo de vídeo (geral/anime/...)
    cutModeChanged = Signal(str)     # modo de corte do anime (ia/tempo)
    fixedDurationChanged = Signal(int)  # duração de cada corte no modo tempo
    subtitleToggled = Signal(bool)   # gerar/queimar legenda automática no corte
    pauseRequested = Signal()
    resumeRequested = Signal()
    cancelRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._source: str | None = None
        self._paused = False
        self._started_at: float | None = None
        self._base_status = "Pronto."
        self._build_ui()
        # Cronômetro: mostra o tempo decorrido para deixar claro que o
        # processamento não travou (etapas longas como o Whisper na CPU).
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._refresh_status_label)

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """Monta o layout da página."""
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Transforme vídeos longos em Shorts virais")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        # -- Tipo de vídeo: ajusta a análise/edição por categoria -------- #
        category_row = QHBoxLayout()
        category_label = QLabel("Tipo de vídeo:")
        category_label.setObjectName("Muted")
        category_row.addWidget(category_label)
        self._category_group = QButtonGroup(self)
        self._category_group.setExclusive(True)
        self._category_buttons: dict[str, QPushButton] = {}
        for slug, label in VIDEO_CATEGORIES.items():
            button = QPushButton(label)
            button.setObjectName("CategoryButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, s=slug: self._on_category_clicked(s)
            )
            self._category_group.addButton(button)
            self._category_buttons[slug] = button
            category_row.addWidget(button)
        category_row.addStretch(1)
        root.addLayout(category_row)

        # -- Legenda: se marcado, o corte sai com legenda queimada -------- #
        subtitle_row = QHBoxLayout()
        self.subtitle_checkbox = QCheckBox("💬 Adicionar legenda ao corte")
        self.subtitle_checkbox.setToolTip(
            "Marcado: gera e queima a legenda automática no vídeo final.\n"
            "Desmarcado: o corte sai sem legenda."
        )
        self.subtitle_checkbox.toggled.connect(self.subtitleToggled.emit)
        subtitle_row.addWidget(self.subtitle_checkbox)
        subtitle_row.addStretch(1)
        root.addLayout(subtitle_row)

        # -- Opções do anime: modo de corte + duração fixa ---------------- #
        self._anime_options = QWidget()
        anime_row = QHBoxLayout(self._anime_options)
        anime_row.setContentsMargins(0, 0, 0, 0)
        mode_label = QLabel("Modo de corte:")
        mode_label.setObjectName("Muted")
        anime_row.addWidget(mode_label)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_buttons: dict[str, QPushButton] = {}
        for slug, label in (
            ("ia", "🤖 IA (melhores momentos)"),
            ("tempo", "⏱ Tempo fixo (divide o episódio)"),
        ):
            button = QPushButton(label)
            button.setObjectName("CategoryButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, m=slug: self._on_mode_clicked(m))
            self._mode_group.addButton(button)
            self._mode_buttons[slug] = button
            anime_row.addWidget(button)
        duration_label = QLabel("Duração de cada corte:")
        duration_label.setObjectName("Muted")
        anime_row.addWidget(duration_label)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(15, 180)
        self.duration_spin.setSingleStep(5)
        self.duration_spin.setValue(60)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setToolTip(
            "Ex.: 60 s gera cortes 0:00-0:59, 1:00-1:59, e assim por diante."
        )
        self.duration_spin.valueChanged.connect(self.fixedDurationChanged.emit)
        anime_row.addWidget(self.duration_spin)
        anime_row.addStretch(1)
        root.addWidget(self._anime_options)
        self.set_category(DEFAULT_VIDEO_CATEGORY)
        self.set_anime_options("ia", 60)

        # -- Entrada: drop area + campo de link ------------------------- #
        self.drop_area = DropArea()
        self.drop_area.fileSelected.connect(self.set_source)
        root.addWidget(self.drop_area)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "Ou cole um link do YouTube (apenas vídeos autorizados por você)..."
        )
        self.url_input.returnPressed.connect(self._use_url)
        url_button = QPushButton("Usar link")
        url_button.clicked.connect(self._use_url)
        url_row.addWidget(self.url_input, stretch=1)
        url_row.addWidget(url_button)
        root.addLayout(url_row)

        self.source_label = QLabel("Nenhum vídeo selecionado.")
        self.source_label.setObjectName("Muted")
        root.addWidget(self.source_label)

        # -- Ações ------------------------------------------------------- #
        actions = QHBoxLayout()
        self.analyze_button = QPushButton("✨ ANALISAR  (Ctrl+Enter)")
        self.analyze_button.setObjectName("Primary")
        self.analyze_button.setEnabled(False)
        self.analyze_button.clicked.connect(self.request_analyze)
        self.pause_button = QPushButton("⏸ Pausar")
        self.pause_button.setVisible(False)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("✖ Cancelar")
        self.cancel_button.setObjectName("Danger")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        actions.addWidget(self.analyze_button, stretch=1)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)

        # -- Progresso ---------------------------------------------------- #
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.status_label = QLabel("Pronto.")
        self.status_label.setObjectName("Muted")
        root.addWidget(self.status_label)

        # -- Resultados + logs (splitter vertical) ------------------------ #
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cards_layout.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.cards_container)
        splitter.addWidget(scroll)

        self.log_panel = LogPanel()
        splitter.addWidget(self.log_panel)
        splitter.setSizes([420, 180])
        root.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------ #
    # API pública (usada pela MainWindow)
    # ------------------------------------------------------------------ #
    def set_category(self, slug: str) -> None:
        """Marca o botão do tipo de vídeo (usado ao restaurar do config)."""
        button = self._category_buttons.get(slug) or self._category_buttons[
            DEFAULT_VIDEO_CATEGORY
        ]
        button.setChecked(True)
        self._anime_options.setVisible(slug == "anime")

    def set_anime_options(self, mode: str, seconds: int) -> None:
        """Restaura o modo de corte e a duração fixa (vindos do config)."""
        button = self._mode_buttons.get(mode) or self._mode_buttons["ia"]
        button.setChecked(True)
        self.duration_spin.setValue(seconds)
        self.duration_spin.setEnabled(mode == "tempo")

    def set_subtitle_enabled(self, enabled: bool) -> None:
        """Restaura o estado do checkbox de legenda (vindo do config)."""
        self.subtitle_checkbox.setChecked(enabled)

    def set_source(self, source: str) -> None:
        """Define o vídeo/URL de origem e habilita o botão Analisar."""
        self._source = source
        display = source if len(source) < 90 else source[:87] + "..."
        self.source_label.setText(f"🎞 {display}")
        self.analyze_button.setEnabled(True)

    def request_analyze(self) -> None:
        """Dispara a análise (também chamada pelo atalho Ctrl+Enter)."""
        if self._source and self.analyze_button.isEnabled():
            self.clear_results()
            self.analyzeRequested.emit(self._source)

    def set_running(self, running: bool) -> None:
        """Alterna o estado visual entre ocioso e processando."""
        self.analyze_button.setEnabled(not running and self._source is not None)
        self.pause_button.setVisible(running)
        self.pause_button.setEnabled(running)
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(running)
        if running:
            self._started_at = time.monotonic()
            self._elapsed_timer.start()
        else:
            self._elapsed_timer.stop()
            self._started_at = None
            self._paused = False
            self.pause_button.setText("⏸ Pausar")

    def set_cancelling(self) -> None:
        """Feedback imediato ao pedir cancelamento (que não é instantâneo:
        etapas como a transcrição precisam terminar antes de abortar)."""
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self._base_status = (
            "Cancelando... aguardando a etapa atual terminar (a transcrição "
            "não pode ser interrompida no meio)."
        )
        self._refresh_status_label()

    def update_progress(self, percent: int, message: str) -> None:
        """Atualiza a barra de progresso e o status."""
        self.progress.setValue(percent)
        self._base_status = message
        self._refresh_status_label()

    def _refresh_status_label(self) -> None:
        """Reescreve o status incluindo o tempo decorrido (prova de vida)."""
        if self._started_at is None:
            self.status_label.setText(self._base_status)
            return
        elapsed = int(time.monotonic() - self._started_at)
        clock = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
        self.status_label.setText(f"{self._base_status}  ⏱ {clock}")

    def add_cut_card(self, cut: CutCandidate) -> None:
        """Insere o card de um corte finalizado."""
        self.cards_layout.addWidget(CutCard(cut))

    def clear_results(self) -> None:
        """Remove todos os cards da análise anterior."""
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    # ------------------------------------------------------------------ #
    def _on_category_clicked(self, slug: str) -> None:
        """Mostra/esconde as opções do anime e propaga a mudança."""
        self._anime_options.setVisible(slug == "anime")
        self.categoryChanged.emit(slug)

    def _on_mode_clicked(self, mode: str) -> None:
        """Habilita a duração apenas no modo tempo fixo e propaga a mudança."""
        self.duration_spin.setEnabled(mode == "tempo")
        self.cutModeChanged.emit(mode)

    def _use_url(self) -> None:
        """Valida e usa o link do YouTube digitado."""
        url = self.url_input.text().strip()
        if is_youtube_url(url):
            self.set_source(url)
        else:
            self.status_label.setText("⚠ Link inválido: cole um link do YouTube.")

    def _toggle_pause(self) -> None:
        """Alterna entre pausar e retomar."""
        self._paused = not self._paused
        if self._paused:
            self.pause_button.setText("▶ Retomar")
            self.pauseRequested.emit()
        else:
            self.pause_button.setText("⏸ Pausar")
            self.resumeRequested.emit()
