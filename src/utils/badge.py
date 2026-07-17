"""Gerador do selo do canal: cartão arredondado com foto redonda, nome e @.

Gerado uma vez ao salvar a página Estilo (thread da GUI) e sobreposto pelo
branding em todos os shorts — o pipeline só consome o PNG pronto.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen

from src.utils.logger import get_logger

logger = get_logger("badge")

_W, _H = 900, 300          # canvas do selo (sobra é transparente)
_RADIUS = 60
_BG = QColor("#FFF6F4")     # cartão claro (como no exemplo)
_NAME_COLOR = QColor("#1D3557")
_HANDLE_COLOR = QColor("#4A7B96")


def generate_badge(
    name: str, handle: str, avatar_path: str, output: str | Path,
) -> Path | None:
    """Desenha o selo e salva como PNG com transparência.

    Returns:
        Caminho do PNG, ou None se não há nada para desenhar.
    """
    name = name.strip()
    handle = handle.strip()
    if not name and not handle:
        return None
    if handle and not handle.startswith("@"):
        handle = f"@{handle}"

    image = QImage(_W, _H, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Cartão arredondado
    card = QRectF(6, 6, _W - 12, _H - 12)
    painter.setPen(QPen(QColor(0, 0, 0, 40), 3))
    painter.setBrush(_BG)
    painter.drawRoundedRect(card, _RADIUS, _RADIUS)

    # Foto do canal em círculo (se existir)
    text_x = 60.0
    avatar = QImage(avatar_path) if avatar_path and Path(avatar_path).exists() else None
    if avatar is not None and not avatar.isNull():
        size = 220.0
        circle = QRectF(40, (_H - size) / 2, size, size)
        clip = QPainterPath()
        clip.addEllipse(circle)
        painter.save()
        painter.setClipPath(clip)
        scaled = avatar.scaled(
            int(size), int(size),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawImage(circle.topLeft(), scaled)
        painter.restore()
        painter.setPen(QPen(QColor(0, 0, 0, 60), 4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle)
        text_x = 300.0
    elif avatar_path:
        logger.warning("Foto do canal não encontrada: %s", avatar_path)

    # Nome (em caixa alta, como nos canais de corte) e @
    if name:
        font = QFont("Segoe UI", 1)
        font.setPixelSize(80)
        font.setWeight(QFont.Weight.Black)
        painter.setFont(font)
        painter.setPen(_NAME_COLOR)
        painter.drawText(
            QRectF(text_x, 55, _W - text_x - 40, 100),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name.upper(),
        )
    if handle:
        font = QFont("Segoe UI", 1)
        font.setPixelSize(52)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(_HANDLE_COLOR)
        y = 160 if name else 100
        painter.drawText(
            QRectF(text_x, y, _W - text_x - 40, 90),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            handle,
        )
    painter.end()

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(output), "PNG"):
        logger.error("Falha ao salvar o selo do canal em %s", output)
        return None
    logger.info("Selo do canal gerado: %s", output)
    return output
