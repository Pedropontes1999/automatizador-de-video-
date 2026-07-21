"""Widget que mostra um frame do vídeo e deixa o usuário arrastar um
retângulo em cima dele (ex.: marcar onde fica uma marca d'água).

As coordenadas expostas (`region`) são sempre na resolução ORIGINAL do
vídeo, já convertidas a partir do tamanho exibido na tela.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import QLabel

_MAX_DISPLAY_WIDTH = 720


class FrameRectSelector(QLabel):
    """QLabel que exibe um frame e captura um retângulo desenhado pelo mouse."""

    regionChanged = Signal(int, int, int, int)  # x, y, w, h (resolução original)

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(200)
        self.setText("Nenhum frame carregado ainda.")
        self.setObjectName("Muted")
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._frame_size: tuple[int, int] | None = None  # (w, h) original
        self._scale: float = 1.0
        self._drag_start: QPoint | None = None
        self._rect_display: QRect | None = None  # em coords do widget

    # ------------------------------------------------------------------ #
    def load_frame(self, image_path: str | Path) -> bool:
        """Carrega o frame extraído do vídeo. Retorna False se falhar."""
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            return False
        self._frame_size = (pixmap.width(), pixmap.height())
        display = pixmap
        if pixmap.width() > _MAX_DISPLAY_WIDTH:
            display = pixmap.scaledToWidth(
                _MAX_DISPLAY_WIDTH, Qt.TransformationMode.SmoothTransformation,
            )
        self._scale = pixmap.width() / display.width()
        self.setPixmap(display)
        self.setFixedSize(display.size())
        self._rect_display = None
        self.update()
        return True

    def set_region(self, x: int, y: int, w: int, h: int) -> None:
        """Preenche o retângulo (coords do vídeo original), ex.: reaproveitar
        a mesma marcação de um vídeo anterior."""
        if self._frame_size is None or self._scale <= 0:
            return
        self._rect_display = QRect(
            round(x / self._scale), round(y / self._scale),
            round(w / self._scale), round(h / self._scale),
        )
        self.update()

    def frame_size(self) -> tuple[int, int] | None:
        """Dimensões (w, h) do frame carregado — nem sempre iguais às que o
        ffprobe reporta pro vídeo (ex.: vídeos com metadado de rotação), por
        isso quem for aplicar o retângulo deve usar ESTA referência, não
        redescobrir a resolução de outro jeito."""
        return self._frame_size

    def region(self) -> tuple[int, int, int, int] | None:
        """Retângulo atual em coordenadas do vídeo original, ou None."""
        if self._rect_display is None or self._frame_size is None:
            return None
        r = self._rect_display.normalized()
        return (
            round(r.x() * self._scale), round(r.y() * self._scale),
            round(r.width() * self._scale), round(r.height() * self._scale),
        )

    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._frame_size is None:
            return
        self._drag_start = event.position().toPoint()
        self._rect_display = QRect(self._drag_start, self._drag_start)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._drag_start is None:
            return
        self._rect_display = QRect(self._drag_start, event.position().toPoint())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt API)
        if self._drag_start is None:
            return
        self._rect_display = QRect(self._drag_start, event.position().toPoint())
        self._drag_start = None
        self.update()
        region = self.region()
        if region is not None:
            self.regionChanged.emit(*region)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt API)
        super().paintEvent(event)
        if self._rect_display is None:
            return
        painter = QPainter(self)
        pen = QPen(QColor(255, 60, 60), 2)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 60, 60, 60))
        painter.drawRect(self._rect_display.normalized())
        painter.end()
