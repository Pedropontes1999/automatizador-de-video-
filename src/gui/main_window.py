"""Janela principal do AUTO SHORTS AI.

Estrutura: sidebar (esquerda) + QStackedWidget com as páginas
(Início, Dashboard, Histórico, Configurações). Gerencia o worker do
pipeline, a fila de tarefas e os atalhos globais.
"""
from __future__ import annotations

from collections import deque

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from src.config.constants import SUPPORTED_VIDEO_EXTENSIONS
from src.config.settings import Settings
from src.database.db import init_database
from src.gui.pages.dashboard_page import DashboardPage
from src.gui.pages.history_page import HistoryPage
from src.gui.pages.home_page import HomePage
from src.gui.pages.settings_page import SettingsPage
from src.gui.pages.style_page import StylePage
from src.gui.theme import build_stylesheet
from src.gui.widgets.sidebar import Sidebar
from src.services.project_service import ProjectService
from src.utils.logger import get_logger
from src.workers.pipeline_worker import PipelineWorker

logger = get_logger("main_window")


class MainWindow(QWidget):
    """Janela raiz da aplicação."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.service = ProjectService(settings)
        self.worker: PipelineWorker | None = None
        self._queue: deque[str] = deque()  # fila de vídeos aguardando

        init_database()
        self._build_ui()
        self._create_shortcuts()
        self.setStyleSheet(build_stylesheet(settings.theme))
        self.setWindowTitle("AUTO SHORTS AI")
        self.resize(1280, 800)

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """Monta sidebar + páginas."""
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        root.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.home = HomePage()
        self.dashboard = DashboardPage()
        self.history = HistoryPage()
        self.style_page = StylePage(self.settings)
        self.settings_page = SettingsPage(self.settings)
        for page in (self.home, self.dashboard, self.history,
                     self.style_page, self.settings_page):
            self.pages.addWidget(page)
        root.addWidget(self.pages, stretch=1)

        # Navegação
        self.sidebar.pageSelected.connect(self.pages.setCurrentIndex)

        # Tipo de vídeo: restaura do config e persiste mudanças
        self.home.set_category(self.settings.video_category)
        self.home.set_anime_options(
            self.settings.anime_cut_mode, self.settings.anime_fixed_seconds,
        )
        self.home.categoryChanged.connect(self._on_category_changed)
        self.home.cutModeChanged.connect(self._on_cut_mode_changed)
        self.home.fixedDurationChanged.connect(self._on_fixed_duration_changed)

        # Fluxo de análise
        self.home.analyzeRequested.connect(self._enqueue_analysis)
        self.home.pauseRequested.connect(self._pause_worker)
        self.home.resumeRequested.connect(self._resume_worker)
        self.home.cancelRequested.connect(self._cancel_worker)

        # Tema dinâmico
        self.settings_page.themeChanged.connect(
            lambda theme: self.setStyleSheet(build_stylesheet(theme))
        )

    def _create_shortcuts(self) -> None:
        """Atalhos globais: Ctrl+O, Ctrl+S, Ctrl+Enter."""
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self._open_file_dialog)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_current_page)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.home.request_analyze)

    def _save_current_page(self) -> None:
        """Ctrl+S: salva a página aberta (Estilo ou Configurações)."""
        if self.pages.currentWidget() is self.style_page:
            self.style_page.save()
        else:
            self.settings_page.save()

    def _on_category_changed(self, category: str) -> None:
        """Persiste o tipo de vídeo escolhido na Home."""
        self.settings.video_category = category
        self.settings.save()
        logger.info("Tipo de vídeo selecionado: %s", category)

    def _on_cut_mode_changed(self, mode: str) -> None:
        """Persiste o modo de corte do anime (ia | tempo)."""
        self.settings.anime_cut_mode = mode
        self.settings.save()
        logger.info("Modo de corte do anime: %s", mode)

    def _on_fixed_duration_changed(self, seconds: int) -> None:
        """Persiste a duração de cada corte no modo tempo fixo."""
        self.settings.anime_fixed_seconds = seconds
        self.settings.save()

    # ------------------------------------------------------------------ #
    # Fila e worker
    # ------------------------------------------------------------------ #
    def _enqueue_analysis(self, source: str) -> None:
        """Adiciona o vídeo à fila; inicia imediatamente se ocioso."""
        if self.worker is not None and self.worker.isRunning():
            self._queue.append(source)
            logger.info("Vídeo adicionado à fila (%d aguardando).", len(self._queue))
            return
        self._start_worker(source)

    def _start_worker(self, source: str) -> None:
        """Cria e inicia o worker do pipeline para um vídeo."""
        self.worker = PipelineWorker(self.service, source)
        self.worker.progressChanged.connect(self._on_progress)
        self.worker.cutFinished.connect(self.home.add_cut_card)
        self.worker.projectFinished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()
        self.home.set_running(True)
        self.dashboard.set_status("Processando")
        logger.info("Processamento iniciado: %s", source)

    def _pause_worker(self) -> None:
        if self.worker is not None:
            self.worker.pause()
            self.dashboard.set_status("Pausado")
            logger.info("Processamento pausado.")

    def _resume_worker(self) -> None:
        if self.worker is not None:
            self.worker.resume_task()
            self.dashboard.set_status("Processando")
            logger.info("Processamento retomado.")

    def _cancel_worker(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.home.set_cancelling()
            self.dashboard.set_status("Cancelando...")
            logger.info(
                "Cancelamento solicitado — aguardando a etapa atual terminar."
            )

    # ------------------------------------------------------------------ #
    # Slots do worker (rodam na main thread)
    # ------------------------------------------------------------------ #
    def _on_progress(self, percent: int, message: str) -> None:
        self.home.update_progress(percent, message)

    def _on_finished(self, project) -> None:
        self.home.set_running(False)
        self.dashboard.set_status("Ocioso")
        self.dashboard.refresh_stats()
        self.history.reload()
        done = sum(1 for c in project.cuts if c.status == "done")
        QMessageBox.information(
            self, "Concluído",
            f"'{project.title}' finalizado!\n{done} cortes exportados para a pasta output/.",
        )
        self._process_next_in_queue()

    def _on_failed(self, message: str) -> None:
        self.home.set_running(False)
        self.home.update_progress(0, "Erro no processamento.")
        self.dashboard.set_status("Erro")
        QMessageBox.warning(self, "Erro no processamento", message)
        self._process_next_in_queue()

    def _on_cancelled(self) -> None:
        self.home.set_running(False)
        self.home.update_progress(0, "Cancelado.")
        self.dashboard.set_status("Ocioso")
        self._process_next_in_queue()

    def _process_next_in_queue(self) -> None:
        """Puxa o próximo vídeo da fila, se houver."""
        if self._queue:
            self._start_worker(self._queue.popleft())

    # ------------------------------------------------------------------ #
    def _open_file_dialog(self) -> None:
        """Atalho Ctrl+O: seleciona vídeo diretamente."""
        patterns = " ".join(f"*{ext}" for ext in SUPPORTED_VIDEO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar vídeo", "", f"Vídeos ({patterns})",
        )
        if path:
            self.home.set_source(path)
            self.pages.setCurrentIndex(0)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Garante que o worker é finalizado antes de fechar."""
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self, "Sair",
                "Há um processamento em andamento. Cancelar e sair?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.cancel()
            # Espera o worker encerrar de forma limpa; se uma etapa longa
            # (ex.: Whisper) não responder, termina à força para nunca
            # crashar com "QThread destroyed while running".
            if not self.worker.wait(8000):
                logger.warning("Worker não respondeu ao cancelamento; terminando.")
                self.worker.terminate()
                self.worker.wait(3000)
        event.accept()
