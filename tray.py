"""
The system tray icon: a little white cat with a Settings, Pause/Resume and Quit menu.
The icon is drawn in code, so Snowcat needs no image files.
"""

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QCursor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap, QPolygonF)
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)  # tray, taskbar, Alt+Tab and large views


class SnowcatTray:
    """Tray icon + menu. Tells the overlay when to pause and the app when to quit."""

    def __init__(self, on_pause_changed, on_quit, on_settings):
        self._on_pause_changed = on_pause_changed
        self._on_settings = on_settings
        self._paused = False

        self._menu = self._build_menu(on_quit)
        self._icon = QSystemTrayIcon(make_snowcat_icon())
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_icon_clicked)
        self._refresh_labels()

    def show(self):
        self._icon.show()

    def hide(self):
        self._icon.hide()

    def _build_menu(self, on_quit):
        """Menu: a 'Snowcat' heading, Settings, Pause/Resume, and Quit."""
        menu = QMenu()
        heading = menu.addAction("Snowcat")
        heading.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Settings…").triggered.connect(self._on_settings)
        self._pause_action = menu.addAction("Pause")
        self._pause_action.triggered.connect(self.toggle_pause)
        menu.addAction("Quit").triggered.connect(on_quit)
        return menu

    def toggle_pause(self):
        """Flip between snowing and paused."""
        self._paused = not self._paused
        self._on_pause_changed(self._paused)
        self._refresh_labels()

    def _refresh_labels(self):
        """Keep the menu text and hover tooltip in sync with the pause state."""
        self._pause_action.setText("Resume" if self._paused else "Pause")
        self._icon.setToolTip("Snowcat - paused" if self._paused else "Snowcat - snowing")

    def _on_icon_clicked(self, reason):
        """A left-click opens the same menu as a right-click; a double-click opens Settings."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._menu.popup(QCursor.pos())
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._menu.hide()
            self._on_settings()


# ----- icon drawing ---------------------------------------------------------

def make_snowcat_icon():
    """Build the tray icon at several sizes so Windows can pick a crisp one."""
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(draw_snowcat_pixmap(size))
    return icon


def draw_snowcat_pixmap(size):
    """The Snowcat logo: a white cat with snow piled on its head, on a snowy night-blue tile.

    Designed on a 64x64 grid. Small sizes (the tray) skip the finest details.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    s = size / 64  # scale from the 64x64 design grid
    detailed = size >= 32

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)

    # Rounded tile: icy blue at the top fading to deep night blue
    tile = QLinearGradient(0, 0, 0, size)
    tile.setColorAt(0, QColor("#6fc3ff"))
    tile.setColorAt(0.55, QColor("#2f73dd"))
    tile.setColorAt(1, QColor("#1c3f9c"))
    painter.setBrush(tile)
    painter.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)

    if detailed:
        # A few falling flakes behind the cat, and a snowflake in the corner
        painter.setBrush(QColor(255, 255, 255, 150))
        for x, y, r in ((9, 12, 1.4), (30, 8, 1.1), (7, 48, 1.2), (57, 44, 1.3), (40, 13, 0.9)):
            painter.drawEllipse(QPointF(x * s, y * s), r * s, r * s)
        _draw_snowflake(painter, s, 53, 12, 5.5)
        painter.setPen(Qt.PenStyle.NoPen)

    # Snow-white cat: ears (pink inside), then a round face
    painter.setBrush(QColor("#f5f8fc"))
    painter.drawPolygon(_poly(s, (11, 36), (14, 11), (30, 24)))
    painter.drawPolygon(_poly(s, (53, 36), (50, 11), (34, 24)))
    painter.setBrush(QColor("#ffb3c6"))
    painter.drawPolygon(_poly(s, (15.5, 29), (16.5, 16.5), (25, 24.5)))
    painter.drawPolygon(_poly(s, (48.5, 29), (47.5, 16.5), (39, 24.5)))
    painter.setBrush(QColor("#f5f8fc"))
    painter.drawEllipse(QPointF(32 * s, 39 * s), 20.5 * s, 17 * s)

    # A pile of snow on its head, with a faint blue edge so it stands out from the white fur
    cap = QPainterPath()
    cap.moveTo(17 * s, 28 * s)
    cap.cubicTo(17 * s, 19 * s, 24 * s, 18.5 * s, 27 * s, 20.5 * s)
    cap.cubicTo(29 * s, 16.5 * s, 36 * s, 16 * s, 38 * s, 20 * s)
    cap.cubicTo(42 * s, 18 * s, 48 * s, 21 * s, 47 * s, 28 * s)
    cap.cubicTo(41 * s, 25.5 * s, 23 * s, 25.5 * s, 17 * s, 28 * s)
    painter.setBrush(QColor("#ffffff"))
    painter.setPen(QPen(QColor("#9cc6ee"), max(1.0, 1.3 * s)))
    painter.drawPath(cap)
    painter.setPen(Qt.PenStyle.NoPen)

    # Eyes with a glint, rosy cheeks and a little pink nose
    painter.setBrush(QColor("#1d2b4a"))
    painter.drawEllipse(QPointF(24 * s, 38 * s), 3.2 * s, 3.8 * s)
    painter.drawEllipse(QPointF(40 * s, 38 * s), 3.2 * s, 3.8 * s)
    if detailed:
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QPointF(25 * s, 36.6 * s), 1.1 * s, 1.1 * s)
        painter.drawEllipse(QPointF(41 * s, 36.6 * s), 1.1 * s, 1.1 * s)
        painter.setBrush(QColor(255, 143, 171, 90))
        painter.drawEllipse(QPointF(18 * s, 45 * s), 3.5 * s, 2.2 * s)
        painter.drawEllipse(QPointF(46 * s, 45 * s), 3.5 * s, 2.2 * s)
    painter.setBrush(QColor("#ff8fab"))
    painter.drawPolygon(_poly(s, (29, 44.5), (35, 44.5), (32, 48)))

    if detailed:
        # Whiskers
        painter.setPen(QPen(QColor(120, 140, 175, 170), max(1.0, 0.9 * s)))
        for side in (-1, 1):
            for dy in (-1.5, 1.5):
                painter.drawLine(QPointF((32 + side * 9) * s, (46 + dy * 0.4) * s),
                                 QPointF((32 + side * 19) * s, (45 + dy * 1.4) * s))

    painter.end()
    return pixmap


def _draw_snowflake(painter, s, x, y, radius):
    """A six-armed snowflake centred at (x, y) on the design grid."""
    painter.setPen(QPen(QColor(255, 255, 255, 235), max(1.0, 1.3 * s), Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    for k in range(6):
        angle = math.pi / 3 * k
        dx, dy = math.cos(angle), math.sin(angle)
        tip = QPointF((x + dx * radius) * s, (y + dy * radius) * s)
        painter.drawLine(QPointF(x * s, y * s), tip)
        for twig in (-0.6, 0.6):  # little V on each arm
            branch = angle + twig
            mid = (x + dx * radius * 0.55, y + dy * radius * 0.55)
            painter.drawLine(QPointF(mid[0] * s, mid[1] * s),
                             QPointF((mid[0] + math.cos(branch) * radius * 0.35) * s,
                                     (mid[1] + math.sin(branch) * radius * 0.35) * s))


def _poly(scale, *points):
    """A polygon from (x, y) points on the 64x64 design grid."""
    return QPolygonF([QPointF(x * scale, y * scale) for x, y in points])
