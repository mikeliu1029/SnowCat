"""
Put a Snowcat shortcut (with the cat logo) on the desktop.

Run it once:   python make_shortcut.py
The shortcut starts Snowcat with pythonw, so no terminal window opens.
"""

import os
import subprocess
import sys

from PyQt6.QtGui import QGuiApplication

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_FILE = os.path.join(HERE, "snowcat.ico")


def save_icon():
    """Save the logo (drawn in tray.py) as a Windows .ico file with several sizes."""
    from PyQt6.QtGui import QImageWriter
    from tray import draw_snowcat_pixmap
    writer = QImageWriter(ICON_FILE, b"ico")
    image = draw_snowcat_pixmap(256).toImage()
    if not writer.write(image):
        sys.exit(f"Couldn't save the icon: {writer.errorString()}")


def pythonw_path():
    """pythonw.exe next to the Python running this script (same packages, no console)."""
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else sys.executable


def make_shortcut():
    desktop = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True, check=True).stdout.strip()
    link = os.path.join(desktop, "Snowcat.lnk")
    script = os.path.join(HERE, "snowcat.py")
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SC_LINK);"
        "$s.TargetPath = $env:SC_TARGET; $s.Arguments = '\"' + $env:SC_SCRIPT + '\"';"
        "$s.WorkingDirectory = $env:SC_DIR; $s.IconLocation = $env:SC_ICON + ',0';"
        "$s.Description = 'Snowcat - snow for your desktop'; $s.Save()"
    )
    env = dict(os.environ, SC_LINK=link, SC_TARGET=pythonw_path(), SC_SCRIPT=script,
               SC_DIR=HERE, SC_ICON=ICON_FILE)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True)
    return link


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    save_icon()
    print("Shortcut created:", make_shortcut())
