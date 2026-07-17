"""Painel de logs em tempo real.

Recebe registros do sistema de logs através de um sinal Qt (thread-safe):
o handler de log pode emitir de qualquer worker thread e o Qt entrega o
sinal na main thread antes de tocar no widget.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit

from src.utils.logger import register_gui_callback

_COLORS = {
    "DEBUG": "#949ba4",
    "INFO": "#f2f3f5",
    "WARNING": "#f0b232",
    "ERROR": "#f23f43",
    "CRITICAL": "#f23f43",
}


class _LogBridge(QObject):
    """Ponte thread-safe entre o logging e o widget."""

    logReceived = Signal(str, str)  # (nível, mensagem)


class LogPanel(QPlainTextEdit):
    """Caixa de texto somente leitura com os logs coloridos por nível."""

    MAX_LINES = 500

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("LogPanel")
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_LINES)

        self._bridge = _LogBridge()
        self._bridge.logReceived.connect(self._append)
        # O callback é chamado pelo QtLogHandler em qualquer thread;
        # emitir o sinal aqui é seguro, o slot roda na main thread.
        register_gui_callback(self._bridge.logReceived.emit)

    def _append(self, level: str, message: str) -> None:
        """Adiciona uma linha colorida ao painel (roda na main thread)."""
        color = _COLORS.get(level, "#f2f3f5")
        self.appendHtml(f'<span style="color:{color}">{message}</span>')
