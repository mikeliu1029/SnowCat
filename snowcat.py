"""
Snowcat - gentle snowfall over your Windows desktop.

A transparent, always-on-top, click-through overlay with falling snow,
plus a system tray icon (Settings / Pause / Quit). The snow:
  - piles up on top of your open windows (and dusts the taskbar),
  - shakes off onto the taskbar when you shake or fling a window,
  - melts away wherever you rest the mouse on it,
  - gets blown around when you swipe the mouse quickly through it,
  - builds a little hat on the mouse pointer when you leave it still,
  - settles on your desktop shortcut icons too,
  - can be knocked flying with snowballs: left-drag on the desktop or
    right-drag anywhere, like a slingshot.

Run it with:   python snowcat.py
"""

import ctypes
import signal
import sys

from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from overlay import SnowOverlay
from settings import Settings
from settings_window import SettingsWindow
from tray import SnowcatTray, make_snowcat_icon

APP_ID = "Snowcat.SnowOverlay"  # tells Windows Snowcat is its own app, not "Python"
INSTANCE_NAME = "SnowcatSingleInstance"  # lets a second launch find the copy already running


def ask_running_copy_to_show_settings():
    """If Snowcat is already running, ask it to open its Settings. True if it answered."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"settings")
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


def listen_for_second_launches(on_launch):
    """Open a little local channel; a second launch knocks on it instead of starting more snow."""
    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_NAME)  # clear a leftover from a crash
    server.listen(INSTANCE_NAME)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), on_launch()))
    return server


def create_app():
    """Create the Qt application. The tray icon, not a window, keeps it alive."""
    # Without this, Windows groups Snowcat under python.exe and shows Python's icon on the taskbar.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(sys.argv)
    app.setApplicationName("Snowcat")
    app.setWindowIcon(make_snowcat_icon())  # the cat logo on the taskbar and in Alt+Tab
    app.setQuitOnLastWindowClosed(False)
    return app


def quit_on_ctrl_c(app):
    """Let Ctrl+C in the terminal close Snowcat cleanly."""
    signal.signal(signal.SIGINT, lambda *_: app.quit())


def main():
    app = create_app()
    if ask_running_copy_to_show_settings():
        return  # already snowing: the running copy just opened its Settings
    quit_on_ctrl_c(app)

    settings = Settings()
    settings.apply_all()  # before the overlay is built, so it starts with the saved amount of snow

    overlay = SnowOverlay(app.primaryScreen())
    settings_window = SettingsWindow(settings, on_changed=overlay.refresh_settings,
                                     on_clear_snow=overlay.clear_snow, on_quit=app.quit)
    tray = SnowcatTray(on_pause_changed=overlay.set_paused, on_quit=app.quit,
                       on_settings=settings_window.open)
    app.aboutToQuit.connect(tray.hide)  # don't leave a ghost icon behind
    app.aboutToQuit.connect(settings.save)
    app.aboutToQuit.connect(overlay.shutdown)  # give the right mouse button back
    server = listen_for_second_launches(settings_window.open)  # noqa: F841 (kept alive while running)

    overlay.show()
    tray.show()
    settings_window.open()  # show the settings on launch; "Done" hides it, the tray icon brings it back

    print(
        f"Snowcat is running with {overlay.flake_count()} flakes. "
        "Shake a window to knock its snow off, hover to melt it, "
        "swipe the mouse to blow flakes around, right-drag (or drag on the desktop) to fling snowballs. "
        "Use the tray icon for settings, pause or quit.",
        flush=True,
    )
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
