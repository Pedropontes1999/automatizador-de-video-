"""Serviço de projetos: caso de uso principal da aplicação.

Une pipeline + banco + plugins em uma única operação chamada pelo worker.
"""
from __future__ import annotations

from src.config.settings import Settings
from src.core.pipeline import PipelineCallbacks, ShortsPipeline
from src.core.task_manager import TaskControl
from src.database.repository import ProjectRepository
from src.models.domain import Project
from src.plugins.plugin_manager import PluginManager
from src.utils.logger import get_logger

logger = get_logger("project_service")


class ProjectService:
    """Executa o processamento completo e persiste o resultado."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.plugins = PluginManager()
        self.plugins.discover()

    def process(
        self, source: str, control: TaskControl, callbacks: PipelineCallbacks,
    ) -> Project:
        """Roda o pipeline para `source`, notifica plugins e salva no banco."""
        self.plugins.emit("on_project_start", source=source)
        pipeline = ShortsPipeline(self.settings, callbacks)
        project = pipeline.run(source, control)
        ProjectRepository.save(project)
        self.plugins.emit("on_project_done", project=project)
        return project
