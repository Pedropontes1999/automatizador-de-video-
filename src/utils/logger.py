"""Sistema de logs central do AUTO SHORTS AI.

- Arquivo rotativo em logs/autoshorts.log (nunca cresce sem limite).
- Console colorido durante o desenvolvimento.
- `QtLogHandler` repassa cada registro para a interface (logs em tempo real)
  através de um callback thread-safe registrado pela GUI.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from typing import Callable

from src.config.constants import LOGS_DIR

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
# Lista (não um único callback): mais de uma página pode ter seu próprio
# LogPanel (ex.: Início e Editor) e todas precisam receber os logs.
_gui_callbacks: list[Callable[[str, str], None]] = []
_configured = False


class QtLogHandler(logging.Handler):
    """Handler que envia logs para a GUI via callback (nível, mensagem)."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        if not _gui_callbacks:
            return
        try:
            message = self.format(record)
        except Exception:  # noqa: BLE001 - log nunca pode derrubar a app
            return
        for callback in list(_gui_callbacks):
            try:
                callback(record.levelname, message)
            except Exception:  # noqa: BLE001 - log nunca pode derrubar a app
                pass


def register_gui_callback(callback: Callable[[str, str], None]) -> None:
    """Registra um callback usado por um painel de logs da interface."""
    _gui_callbacks.append(callback)


def _configure_root() -> None:
    """Configura o logger raiz uma única vez (arquivo + console + GUI)."""
    global _configured
    if _configured:
        return
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("autoshorts")
    root.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        LOGS_DIR / "autoshorts.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    file_handler.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    console.setLevel(logging.INFO)

    gui = QtLogHandler()
    gui.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    gui.setLevel(logging.INFO)

    root.addHandler(file_handler)
    root.addHandler(console)
    root.addHandler(gui)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger filho de 'autoshorts' já configurado."""
    _configure_root()
    return logging.getLogger(f"autoshorts.{name}")
