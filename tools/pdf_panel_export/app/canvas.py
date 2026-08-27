from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPixmap, QPen, QBrush, QColor
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsSimpleTextItem,
)

from .constants import ASPECT_W, ASPECT_H

NUDGE_STEP = 1
NUDGE_STEP_FAST = 10

_ARROW_DELTAS = {
    Qt.Key.Key_Left: (-1, 0),
    Qt.Key.Key_Right: (1, 0),
    Qt.Key.Key_Up: (0, -1),
    Qt.Key.Key_Down: (0, 1),
}


def _clamp_to_bounds(start: QPointF, w: float, h: float, dx_positive: bool,
                      dy_positive: bool, bounds: QRectF) -> tuple[float, float]:
    """Scale (w, h) down (keeping the 16:9 ratio) so the rect anchored at
    `start` and growing in the given directions stays inside `bounds`."""
    max_w = (bounds.right() - start.x()) if dx_positive else (start.x() - bounds.left())
    max_h = (bounds.bottom() - start.y()) if dy_positive else (start.y() - bounds.top())
    max_w = max(max_w, 0.0)
    max_h = max(max_h, 0.0)

    scale_w = (max_w / w) if w > 0 else float("inf")
    scale_h = (max_h / h) if h > 0 else float("inf")
    scale = min(1.0, scale_w, scale_h)
    return w * scale, h * scale


def compute_constrained_rect(start: QPointF, current: QPointF, bounds: QRectF) -> QRectF:
    """Build a rectangle anchored at `start`, sized towards `current`,
    forced to a 16:9 aspect ratio, clamped inside `bounds`."""
    dx = current.x() - start.x()
    dy = current.y() - start.y()

    w_from_dx = abs(dx)
    h_from_dx = w_from_dx * ASPECT_H / ASPECT_W
    h_from_dy = abs(dy)
    w_from_dy = h_from_dy * ASPECT_W / ASPECT_H

    if w_from_dx >= w_from_dy:
        w, h = w_from_dx, h_from_dx
    else:
        w, h = w_from_dy, h_from_dy

    dx_positive = dx >= 0
    dy_positive = dy >= 0

    w, h = _clamp_to_bounds(start, w, h, dx_positive, dy_positive, bounds)

    x0 = start.x() if dx_positive else start.x() - w
    y0 = start.y() if dy_positive else start.y() - h
    return QRectF(x0, y0, w, h)


class PdfCanvas(QGraphicsView):
    """Displays one rendered PDF page and lets the user drag out a
    16:9-locked crop rectangle on top of it."""

    selectionChanged = Signal(QRectF)
    presetDragFinished = Signal(QRectF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(self.renderHints())
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._pixmap_item = None
        self._bounds = QRectF()

        self._selection_item = QGraphicsRectItem()
        self._selection_item.setPen(QPen(QColor(255, 60, 60), 2, Qt.PenStyle.DashLine))
        self._selection_item.setBrush(QBrush(QColor(255, 60, 60, 60)))
        self._selection_item.setZValue(10)
        self._selection_item.setVisible(False)
        self._scene.addItem(self._selection_item)

        self._region_items: list = []

        self._dragging = False
        self._drag_is_preset = False
        self._drag_start = QPointF()
        self._suppress_signal = False

        self._moving = False
        self._move_start = QPointF()
        self._move_rect_start = QRectF()

        self.setMouseTracking(True)

    def load_page(self, qpixmap: QPixmap):
        if self._pixmap_item is not None:
            self._scene.removeItem(self._pixmap_item)
        self._pixmap_item = self._scene.addPixmap(qpixmap)
        self._pixmap_item.setZValue(0)
        self._bounds = QRectF(0, 0, qpixmap.width(), qpixmap.height())
        self._scene.setSceneRect(self._bounds)
        self._selection_item.setVisible(False)
        self.fit_page()

    def fit_page(self):
        if self._pixmap_item is not None:
            self.fitInView(self._bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_page()

    @property
    def bounds(self) -> QRectF:
        return self._bounds

    def set_reference_regions(self, regions: list[tuple[str, QRectF]]):
        """Draw the saved (non-active) crop regions as a permanent green
        overlay so the user can see them while positioning new ones."""
        for item in self._region_items:
            self._scene.removeItem(item)
        self._region_items = []

        for tag, rect in regions:
            rect_item = QGraphicsRectItem(rect)
            rect_item.setPen(QPen(QColor(50, 160, 70), 2, Qt.PenStyle.SolidLine))
            rect_item.setBrush(QBrush(QColor(50, 160, 70, 40)))
            rect_item.setZValue(5)
            self._scene.addItem(rect_item)
            self._region_items.append(rect_item)

            label = QGraphicsSimpleTextItem(tag)
            label.setBrush(QBrush(QColor(20, 100, 30)))
            label.setPos(rect.x() + 4, rect.y() + 2)
            label.setZValue(6)
            self._scene.addItem(label)
            self._region_items.append(label)

    def selection_rect(self) -> QRectF:
        return self._selection_item.rect()

    def set_selection_rect(self, rect: QRectF, emit: bool = False):
        rect = rect.intersected(self._bounds) if not self._bounds.isEmpty() else rect
        self._suppress_signal = True
        self._selection_item.setRect(rect)
        self._selection_item.setVisible(rect.width() > 0 and rect.height() > 0)
        self._suppress_signal = False
        if emit:
            self.selectionChanged.emit(rect)

    def _clamp_rect_position(self, rect: QRectF) -> QRectF:
        x = min(max(rect.x(), self._bounds.left()), self._bounds.right() - rect.width())
        y = min(max(rect.y(), self._bounds.top()), self._bounds.bottom() - rect.height())
        return QRectF(x, y, rect.width(), rect.height())

    def mousePressEvent(self, event):
        button = event.button()
        if self._pixmap_item is None or button not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            return super().mousePressEvent(event)
        pos = self.mapToScene(event.pos())
        if not self._bounds.contains(pos):
            return super().mousePressEvent(event)

        if (button == Qt.MouseButton.LeftButton and self._selection_item.isVisible()
                and self._selection_item.rect().contains(pos)):
            self._moving = True
            self._move_start = pos
            self._move_rect_start = QRectF(self._selection_item.rect())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        self._dragging = True
        self._drag_is_preset = button == Qt.MouseButton.RightButton
        self._drag_start = pos
        self.set_selection_rect(QRectF(pos, pos))

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.pos())

        if self._moving:
            delta = pos - self._move_start
            rect = QRectF(self._move_rect_start)
            rect.translate(delta)
            rect = self._clamp_rect_position(rect)
            self.set_selection_rect(rect, emit=True)
            return

        if self._dragging:
            rect = compute_constrained_rect(self._drag_start, pos, self._bounds)
            self.set_selection_rect(rect, emit=True)
            return

        if self._pixmap_item is not None and self._selection_item.isVisible() and self._selection_item.rect().contains(pos):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._moving and event.button() == Qt.MouseButton.LeftButton:
            self._moving = False
            self.unsetCursor()
            self.selectionChanged.emit(self._selection_item.rect())
            return

        if self._dragging and event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._dragging = False
            rect = self._selection_item.rect()
            self.selectionChanged.emit(rect)
            if self._drag_is_preset and rect.width() > 1 and rect.height() > 1:
                self.presetDragFinished.emit(rect)
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        delta = _ARROW_DELTAS.get(event.key())
        if self._pixmap_item is None or delta is None or not self._selection_item.isVisible():
            return super().keyPressEvent(event)

        step = NUDGE_STEP_FAST if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else NUDGE_STEP
        rect = QRectF(self._selection_item.rect())
        rect.translate(delta[0] * step, delta[1] * step)
        rect = self._clamp_rect_position(rect)
        self.set_selection_rect(rect, emit=True)
