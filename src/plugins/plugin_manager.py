"""Arquitetura de plugins do AUTO SHORTS AI.

Qualquer arquivo `plugin_*.py` nesta pasta que defina uma classe herdando de
`PluginBase` é carregado automaticamente na inicialização. Plugins recebem
eventos do ciclo de vida (hooks) e podem estender o comportamento sem tocar
no núcleo da aplicação.

Hooks disponíveis:
- on_app_start()
- on_project_start(source: str)
- on_project_done(project: Project)
- on_cut_exported(cut: CutCandidate)
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from src.config.constants import PLUGINS_DIR
from src.utils.logger import get_logger

logger = get_logger("plugins")


class PluginBase:
    """Classe base de todo plugin. Sobrescreva os hooks que interessarem."""

    #: Nome exibido nos logs.
    name: str = "plugin"
    #: Versão do plugin.
    version: str = "1.0"

    def on_app_start(self) -> None:  # noqa: D102
        pass

    def on_project_start(self, source: str) -> None:  # noqa: D102
        pass

    def on_project_done(self, project) -> None:  # noqa: D102
        pass

    def on_cut_exported(self, cut) -> None:  # noqa: D102
        pass


class PluginManager:
    """Descobre, instancia e despacha eventos para os plugins."""

    def __init__(self) -> None:
        self._plugins: list[PluginBase] = []

    def discover(self) -> None:
        """Carrega todos os arquivos plugin_*.py da pasta de plugins."""
        for file in sorted(Path(PLUGINS_DIR).glob("plugin_*.py")):
            try:
                self._load_file(file)
            except Exception as exc:  # noqa: BLE001 - plugin ruim não derruba a app
                logger.error("Falha ao carregar plugin %s: %s", file.name, exc)
        logger.info("Plugins carregados: %d", len(self._plugins))

    def _load_file(self, file: Path) -> None:
        """Importa o módulo e instancia as classes PluginBase encontradas."""
        spec = importlib.util.spec_from_file_location(file.stem, file)
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, PluginBase) and cls is not PluginBase:
                self._plugins.append(cls())
                logger.info("Plugin ativo: %s v%s", cls.name, cls.version)

    def emit(self, hook: str, **kwargs) -> None:
        """Chama o hook em todos os plugins, isolando falhas individuais."""
        for plugin in self._plugins:
            try:
                getattr(plugin, hook)(**kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.error("Plugin '%s' falhou em %s: %s", plugin.name, hook, exc)
