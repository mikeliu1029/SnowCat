"""
The snow overlay: a borderless, see-through window that covers the whole
screen, stays above other windows, and lets every mouse click fall through
to the apps underneath.

Every frame it looks up where the other windows and the mouse are, so snow
can settle on windows, fall off when they're shaken, melt under the mouse,
and get blown around by fast mouse swipes.
"""

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QApplication, QWidget

import snowballs
import snowcover
import win32_helpers
from desktopicons import IconWatcher
from mousehook import RightDragCatcher
from snowballs import SnowballLauncher
from snowcover import SnowCover
from snowfall import Snowfall

FRAME_INTERVAL_MS = 16          # ~60 frames per second
KEEP_ON_TOP_INTERVAL_MS = 2000  # re-claim the top spot every couple of seconds
MAX_FRAME_SECONDS = 0.05        # cap slow frames so flakes never jump


class SnowOverlay(QWidget):
    """Full-screen transparent window that the snow is drawn on."""

    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self._last_frame_time = None
        self._hwnd = None
        self._cursor = None  # mouse position in overlay pixels, or None if unknown

        self._setup_window_flags()
        self.setGeometry(screen.geometry())
        self.snowfall = Snowfall(self.width(), self.height(), screen.devicePixelRatio())
        self.snowcover = SnowCover(self.width(), self.height(), screen.devicePixelRatio())
        self.snowballs = SnowballLauncher(self.snowcover, self.snowfall, screen.devicePixelRatio())

        self._icons = IconWatcher()  # desktop shortcut positions, read in the background
        self._icons.start()
        self._right_drag = RightDragCatcher(should_catch=self._can_catch_right_drag)
        self._left_was_down = False

        self._frame_timer = self._start_timer(FRAME_INTERVAL_MS, self._advance_frame)
        self._top_timer = self._start_timer(KEEP_ON_TOP_INTERVAL_MS, self._stay_on_top)
        screen.geometryChanged.connect(self._fit_to_screen)

    # ----- window setup -------------------------------------------------

    def _setup_window_flags(self):
        """Make the window borderless, transparent, topmost and click-through."""
        self.setWindowTitle("Snowcat overlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint          # no title bar or border
            | Qt.WindowType.WindowStaysOnTopHint       # above normal windows
            | Qt.WindowType.Tool                       # no taskbar button / Alt+Tab entry
            | Qt.WindowType.WindowTransparentForInput  # mouse input passes through
            | Qt.WindowType.WindowDoesNotAcceptFocus   # never steals keyboard focus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def showEvent(self, event):
        """Once the real Win32 window exists, make sure it is click-through and on top."""
        super().showEvent(event)
        win32_helpers.make_click_through(self.hwnd())
        win32_helpers.bring_to_top(self.hwnd())
        if not self._right_drag.start():
            print("Snowcat couldn't watch the right mouse button; "
                  "snowballs can still be flung from the desktop.", flush=True)

    def closeEvent(self, event):
        """If anything closes the overlay window, shut Snowcat down cleanly."""
        super().closeEvent(event)
        QApplication.quit()

    def shutdown(self):
        """Give the mouse back and stop watching the desktop icons."""
        self._right_drag.stop()
        self._icons.stop()

    def hwnd(self):
        """The native Win32 handle of this window."""
        if self._hwnd is None:
            self._hwnd = int(self.winId())
        return self._hwnd

    def _start_timer(self, interval_ms, callback):
        """Create and start a repeating timer owned by this window."""
        timer = QTimer(self)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.timeout.connect(callback)
        timer.start(interval_ms)
        return timer

    def _fit_to_screen(self, geometry):
        """Follow screen resolution changes."""
        self.setGeometry(geometry)
        self.snowfall.resize(geometry.width(), geometry.height())
        self.snowcover.resize(geometry.width(), geometry.height())

    def _stay_on_top(self):
        """Other 'topmost' windows (like the taskbar) can rise above us; take the top back."""
        win32_helpers.bring_to_top(self.hwnd())

    # ----- animation ----------------------------------------------------

    def set_paused(self, paused):
        """Freeze or resume the snow. While frozen, nothing is redrawn (no CPU used)."""
        if paused:
            self._frame_timer.stop()
        else:
            self._last_frame_time = None  # don't treat the pause as one giant frame
            self._cursor = None
            self.snowcover.forget_motion()  # windows moved while paused aren't being shaken
            self.snowballs.cancel()
            self._frame_timer.start()

    def refresh_settings(self):
        """Settings changed: update the things that don't pick them up on their own."""
        self.snowfall.refresh()
        self.snowcover.refresh()
        self.update()

    def clear_snow(self):
        self.snowcover.clear_all()
        self.update()

    def flake_count(self):
        return len(self.snowfall.flakes)

    def _advance_frame(self):
        """Move the snow forward by the real time since the last frame, then repaint."""
        now = time.perf_counter()
        if self._last_frame_time is not None:
            self._step(min(now - self._last_frame_time, MAX_FRAME_SECONDS))
        self._last_frame_time = now
        self.update()

    def _step(self, dt):
        """Follow the windows and the mouse, then move all the snow forward by dt seconds."""
        windows = win32_helpers.visible_windows(skip_hwnd=self.hwnd())
        to_local = self._physical_to_local()
        self._icons.enabled = snowcover.ICONS_ENABLED
        icons = self._icons.icons if snowcover.ICONS_ENABLED else ()
        self.snowcover.follow_windows(windows, to_local, dt, icons)

        screen_cursor = win32_helpers.cursor_position()
        cursor = to_local(*screen_cursor) if screen_cursor else None
        if cursor and self._cursor:
            self.snowfall.blow(*self._cursor, *cursor, dt)
        self._cursor = cursor

        self.snowcover.follow_cursor(cursor, dt)
        magnet = self.snowcover.cursor_snow.magnet()
        if magnet:
            self.snowfall.attract(*magnet, dt)  # resting mouse: flakes drift onto it

        self.snowfall.update(dt, catch=self.snowcover.catch_flake)
        self.snowcover.update(dt, cursor)
        self._follow_slingshot(cursor, screen_cursor, to_local)
        self.snowballs.update(dt, cursor)

    def _follow_slingshot(self, cursor, screen_cursor, to_local):
        """Start and release slingshot pulls: left-drag on the desktop, or right-drag anywhere."""
        balls = self.snowballs
        left_down = win32_helpers.primary_button_down()
        if (left_down and not self._left_was_down and cursor and not balls.aiming
                and win32_helpers.is_desktop_at(*screen_cursor)):
            balls.begin_aim(cursor, "left")
        elif not left_down and balls.source == "left":
            balls.release()
        self._left_was_down = left_down

        anchor = self._right_drag.anchor
        if anchor and not balls.aiming:
            balls.begin_aim(to_local(*anchor), "right")
        if self._right_drag.take_release() and balls.source == "right":
            balls.release()

    def _can_catch_right_drag(self, x, y):
        """Asked by the mouse hook on each right press: may this become a slingshot pull?

        Not while paused, while the pointer is hidden, or in full-screen apps
        (in games the right button usually means "aim" and must work normally).
        """
        return (snowballs.SLINGSHOT_ENABLED and self._frame_timer.isActive()
                and win32_helpers.cursor_position() is not None
                and not win32_helpers.foreground_is_fullscreen())

    def _physical_to_local(self):
        """A converter from Win32 screen pixels to this window's (DPI-scaled) pixels."""
        scale = 1 / self._screen.devicePixelRatio()
        origin_x, origin_y = self.x(), self.y()
        return lambda x, y: (x * scale - origin_x, y * scale - origin_y)

    def paintEvent(self, event):
        """Draw the snow. Anything we don't paint stays fully transparent."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.snowcover.draw_piles(painter)
        self.snowfall.draw(painter)
        self.snowcover.draw_loose_snow(painter)
        self.snowballs.draw(painter)
        painter.end()
