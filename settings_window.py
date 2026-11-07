"""
The Settings window: sliders and switches for everything in settings.py.

Changes apply straight away (no OK button) and are saved a moment later.
Open it from the tray menu, or by double-clicking the tray icon.
"""

from PyQt6.QtCore import QPropertyAnimation, QRectF, QSize, Qt, QTimer, pyqtProperty
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QSlider, QVBoxLayout, QWidget)

from settings import BY_KEY, SECTIONS, SETTINGS
from tray import draw_snowcat_pixmap, make_snowcat_icon

SAVE_DELAY_MS = 400  # wait for a slider to stop moving before writing the file

STYLE = """
QWidget#window { background: #0e1a2b; }
QWidget { color: #e6eefb; font-family: "Segoe UI"; font-size: 10pt; }
QLabel#title { font-size: 17pt; font-weight: 600; color: #ffffff; }
QLabel#subtitle { color: #8ea3c0; }
QLabel#section { font-size: 8.5pt; font-weight: 700; color: #7cc8ff; letter-spacing: 1px; }
QFrame#card { background: #15263d; border: 1px solid #213756; border-radius: 12px; }
QFrame#divider { background: #213756; max-height: 1px; min-height: 1px; border: none; }
QLabel#label { font-weight: 600; }
QLabel#help { color: #8ea3c0; font-size: 9pt; }
QLabel#value { color: #7cc8ff; font-weight: 600; }
QLabel:disabled { color: #4f627d; }
QScrollArea, QWidget#content { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2a4266; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSlider::groove:horizontal { height: 6px; background: #263b5a; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #5fb4f5; border-radius: 3px; }
QSlider::handle:horizontal { background: #ffffff; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: #dff1ff; }
QSlider::sub-page:horizontal:disabled { background: #34465f; }
QSlider::handle:horizontal:disabled { background: #6b7a90; }
QPushButton { background: #1d3351; border: 1px solid #2c4870; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { background: #24406a; }
QPushButton:pressed { background: #18304f; }
QPushButton#primary { background: #4aa3ea; border-color: #4aa3ea; color: #06121f; font-weight: 600; }
QPushButton#primary:hover { background: #63b3f0; }
QPushButton#quit { background: transparent; border-color: #6b3446; color: #ff9db3; padding: 5px 12px; }
QPushButton#quit:hover { background: #3a1d2a; border-color: #a04a63; color: #ffc2d0; }
"""


class ToggleSwitch(QAbstractButton):
    """A sliding on/off switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._position = 0.0  # 0 = off, 1 = on (animated in between)
        self._slide = QPropertyAnimation(self, b"position", self)
        self._slide.setDuration(140)
        self.toggled.connect(self._animate)

    def set_now(self, checked):
        """Set the switch without animating (used when the window first fills in)."""
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._position = 1.0 if checked else 0.0
        self.update()

    def _get_position(self):
        return self._position

    def _set_position(self, value):
        self._position = value
        self.update()

    position = pyqtProperty(float, _get_position, _set_position)

    def _animate(self, checked):
        self._slide.stop()
        self._slide.setStartValue(self._position)
        self._slide.setEndValue(1.0 if checked else 0.0)
        self._slide.start()

    def sizeHint(self):
        return QSize(44, 24)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        off, on = QColor("#34486a"), QColor("#4aa3ea")
        t = self._position
        track = QColor(round(off.red() + (on.red() - off.red()) * t),
                       round(off.green() + (on.green() - off.green()) * t),
                       round(off.blue() + (on.blue() - off.blue()) * t))
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, 44, 24), 12, 12)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(3 + 20 * t, 3, 18, 18))
        painter.end()


class SettingRow(QWidget):
    """One setting: its name, a short explanation, and a slider or switch."""

    def __init__(self, setting, settings, on_change):
        super().__init__()
        self.setting = setting
        self._settings = settings
        self._on_change = on_change

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(10)
        self._label = _label(setting.label, "label")
        top.addWidget(self._label, 1)
        layout.addLayout(top)
        self._help = _label(setting.help, "help")
        self._help.setWordWrap(True)

        if setting.is_switch:
            self._control = ToggleSwitch()
            self._control.toggled.connect(self._switched)
            top.addWidget(self._control)
            layout.addWidget(self._help)
        else:
            self._value = _label("", "value")
            top.addWidget(self._value)
            layout.addWidget(self._help)
            self._control = QSlider(Qt.Orientation.Horizontal)
            self._control.setCursor(Qt.CursorShape.PointingHandCursor)
            self._control.setRange(0, round((setting.high - setting.low) / setting.step))
            self._control.valueChanged.connect(self._slid)
            layout.addSpacing(4)
            layout.addWidget(self._control)
        self.refresh()

    def refresh(self):
        """Show the current value (after opening the window or resetting)."""
        value = self._settings.get(self.setting.key)
        if self.setting.is_switch:
            self._control.set_now(value)
        else:
            self._control.blockSignals(True)
            self._control.setValue(round((value - self.setting.low) / self.setting.step))
            self._control.blockSignals(False)
            self._value.setText(self.setting.describe(value))

    def _slid(self, position):
        s = self.setting
        value = round(s.low + position * s.step, 4)
        if isinstance(s.default, int):
            value = int(round(value))
        self._value.setText(s.describe(value))
        self._settings.set(s.key, value)
        self._on_change(s.key)

    def _switched(self, checked):
        self._settings.set(self.setting.key, checked)
        self._on_change(self.setting.key)


class SettingsWindow(QWidget):
    """The Settings window. Only one is ever made; open() just shows it again."""

    def __init__(self, settings, on_changed, on_clear_snow, on_quit):
        super().__init__()
        self._settings = settings
        self._on_changed = on_changed
        self._rows = []

        self.setObjectName("window")
        self.setWindowTitle("Snowcat settings")
        self.setWindowIcon(make_snowcat_icon())
        self.setStyleSheet(STYLE)
        self.resize(470, 720)
        self.setMinimumSize(400, 420)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(settings.save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        layout.addLayout(self._build_header(on_quit))
        layout.addWidget(self._build_sections(), 1)
        layout.addLayout(self._build_footer(on_clear_snow))
        self._update_enabled()

    def open(self):
        """Show the window and bring it to the front."""
        for row in self._rows:
            row.refresh()
        self._update_enabled()
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    # ----- layout -----

    def _build_header(self, on_quit):
        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(draw_snowcat_pixmap(48))
        header.addWidget(icon)
        words = QVBoxLayout()
        words.setSpacing(0)
        words.addWidget(_label("Snowcat", "title"))
        words.addWidget(_label("Changes apply as you make them.", "subtitle"))
        header.addLayout(words, 1)
        quit_button = QPushButton("Quit Snowcat")
        quit_button.setObjectName("quit")
        quit_button.setToolTip("Stop the snow and close Snowcat completely")
        quit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        quit_button.clicked.connect(on_quit)
        header.addWidget(quit_button, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _build_sections(self):
        content = QWidget()
        content.setObjectName("content")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(8)
        for section in SECTIONS:
            column.addSpacing(6)
            column.addWidget(_label(section.upper(), "section"))
            column.addWidget(self._build_card(section))
        column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_card(self, section):
        card = QFrame()
        card.setObjectName("card")
        rows = QVBoxLayout(card)
        rows.setContentsMargins(16, 14, 16, 14)
        rows.setSpacing(12)
        for i, setting in enumerate(s for s in SETTINGS if s.section == section):
            if i:
                divider = QFrame()
                divider.setObjectName("divider")
                rows.addWidget(divider)
            row = SettingRow(setting, self._settings, self._changed)
            self._rows.append(row)
            rows.addWidget(row)
        return card

    def _build_footer(self, on_clear_snow):
        footer = QHBoxLayout()
        footer.setSpacing(8)
        clear = QPushButton("Clear all snow")
        clear.setToolTip("Melt every pile away right now")
        clear.clicked.connect(on_clear_snow)
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.close)
        for button in (clear, reset):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            footer.addWidget(button)
        footer.addStretch(1)
        done.setCursor(Qt.CursorShape.PointingHandCursor)
        footer.addWidget(done)
        return footer

    # ----- reacting -----

    def _changed(self, key):
        if BY_KEY[key].is_switch:
            self._update_enabled()
        self._on_changed()
        self._save_timer.start(SAVE_DELAY_MS)

    def _reset(self):
        self._settings.reset()
        for row in self._rows:
            row.refresh()
        self._update_enabled()
        self._on_changed()
        self._save_timer.start(SAVE_DELAY_MS)

    def _update_enabled(self):
        """Grey out sliders whose feature is switched off."""
        for row in self._rows:
            needed = row.setting.requires
            row.setEnabled(needed is None or bool(self._settings.get(needed)))

    def closeEvent(self, event):
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._settings.save()
        event.accept()  # just hides the window; Snowcat keeps running


def _label(text, name):
    label = QLabel(text)
    label.setObjectName(name)
    return label
