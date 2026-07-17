"""Plugin de exemplo: demonstra a arquitetura de plugins.

Copie este arquivo (mantendo o prefixo `plugin_`) para criar seus próprios
plugins — eles são carregados automaticamente na inicialização.
"""
from __future__ import annotations

from src.plugins.plugin_manager import PluginBase
from src.utils.logger import get_logger

logger = get_logger("plugin.exemplo")


class ExamplePlugin(PluginBase):
    """Loga os eventos do ciclo de vida do processamento."""

    name = "exemplo"
    version = "1.0"

    def on_project_start(self, source: str) -> None:
        """Chamado quando um novo processamento começa."""
        logger.info("[plugin exemplo] Projeto iniciado: %s", source)

    def on_project_done(self, project) -> None:
        """Chamado quando o processamento termina."""
        logger.info(
            "[plugin exemplo] Projeto '%s' concluído com %d cortes.",
            project.title, len(project.cuts),
        )
