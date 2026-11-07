"""
Small wrappers around the Win32 calls Snowcat needs.

pywin32 sets up the overlay's own window. The window scan below uses ctypes
directly instead, because it runs every frame and needs to be quick
(about half a millisecond for a whole desktop).
"""

import ctypes
from collections import namedtuple
from ctypes import wintypes

import win32api
import win32con
import win32gui

# Extended window styles that make a window invisible to the mouse.
CLICK_THROUGH_STYLES = (
    win32con.WS_EX_LAYERED        # per-pixel transparency
    | win32con.WS_EX_TRANSPARENT  # mouse clicks go to whatever is underneath
    | win32con.WS_EX_TOOLWINDOW   # hidden from the taskbar and Alt+Tab
    | win32con.WS_EX_NOACTIVATE   # can never become the focused window
)


def make_click_through(hwnd):
    """Add the click-through styles to a window (Qt sets most already; this makes sure)."""
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    if style & CLICK_THROUGH_STYLES != CLICK_THROUGH_STYLES:
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | CLICK_THROUGH_STYLES)


def bring_to_top(hwnd):
    """Move a window to the top of the 'always on top' layer without focusing it."""
    win32gui.SetWindowPos(
        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
    )


# ----- finding the windows on screen ----------------------------------------

ROLE_WINDOW = "window"    # an ordinary app window: snow can settle on its top edge
ROLE_TASKBAR = "taskbar"  # the taskbar: snow shaken off windows lands on it
ROLE_BLOCKER = "blocker"  # Start menu, Alt+Tab and friends: hide snow behind them, collect none

TASKBAR_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
DESKTOP_CLASSES = {"Progman", "WorkerW"}  # the desktop (wallpaper and icons)
SHELL_POPUP_CLASSES = {
    "Windows.UI.Core.CoreWindow",           # Start, Search, notification centre
    "XamlExplorerHostIslandWindow",         # Alt+Tab, Task View, snap layouts
    "MultitaskingViewFrame",                # older Alt+Tab
    "ForegroundStaging",
    "NotifyIconOverflowWindow",             # hidden tray icons
    "TopLevelWindowForOverflowXamlIsland",
}
MIN_WINDOW_SIZE = 40  # px; skip slivers and hidden helper windows

WindowBox = namedtuple("WindowBox", "hwnd left top right bottom role")
WindowBox.__doc__ = "One visible window's on-screen box, in physical pixels."

_GWL_EXSTYLE = -20
_LWA_ALPHA = 0x2
_DWMWA_EXTENDED_FRAME_BOUNDS = 9  # the box you actually see, without invisible resize borders
_DWMWA_CLOAKED = 14               # hidden by Windows, e.g. on another virtual desktop
_CURSOR_SHOWING = 0x1
_SM_SWAPBUTTON = 23
_VK_LBUTTON, _VK_RBUTTON = 0x01, 0x02
_GA_ROOT = 2

_user32 = ctypes.WinDLL("user32")
_dwmapi = ctypes.WinDLL("dwmapi")
_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class _CursorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hCursor", wintypes.HANDLE), ("ptScreenPos", wintypes.POINT)]


_user32.GetCursorInfo.argtypes = (ctypes.POINTER(_CursorInfo),)
_user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
_user32.WindowFromPoint.argtypes = (wintypes.POINT,)
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetAncestor.argtypes = (wintypes.HWND, ctypes.c_uint)
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetForegroundWindow.restype = wintypes.HWND

_user32.EnumWindows.argtypes = (_EnumWindowsProc, wintypes.LPARAM)
_user32.IsWindowVisible.argtypes = (wintypes.HWND,)
_user32.IsIconic.argtypes = (wintypes.HWND,)
_user32.IsWindow.argtypes = (wintypes.HWND,)
_user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
_user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_user32.GetLayeredWindowAttributes.argtypes = (
    wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(wintypes.DWORD),
)
_dwmapi.DwmGetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


def visible_windows(skip_hwnd=None):
    """Every window you can see, top-most first (the order Windows stacks them)."""
    found = []
    class_name = ctypes.create_unicode_buffer(256)

    def visit(hwnd, _lparam):
        if hwnd and hwnd != skip_hwnd and _is_showing(hwnd):
            role = _role_of(hwnd, class_name)
            if role:
                left, top, right, bottom = _frame_bounds(hwnd)
                if right - left >= MIN_WINDOW_SIZE and bottom - top >= MIN_WINDOW_SIZE:
                    found.append(WindowBox(hwnd, left, top, right, bottom, role))
        return True

    _user32.EnumWindows(_EnumWindowsProc(visit), 0)
    return found


def window_exists(hwnd):
    """False once a window has been closed."""
    return bool(_user32.IsWindow(hwnd))


def cursor_position():
    """The mouse position in physical screen pixels.

    None while the pointer is hidden (typing, games, lock screen), so snow
    never piles up on an invisible cursor.
    """
    info = _CursorInfo(cbSize=ctypes.sizeof(_CursorInfo))
    if _user32.GetCursorInfo(ctypes.byref(info)) and info.flags & _CURSOR_SHOWING:
        return info.ptScreenPos.x, info.ptScreenPos.y
    return None


def primary_button_down():
    """True while the main mouse button is held (the right one if the buttons are swapped)."""
    button = _VK_RBUTTON if _user32.GetSystemMetrics(_SM_SWAPBUTTON) else _VK_LBUTTON
    return bool(_user32.GetAsyncKeyState(button) & 0x8000)


def is_desktop_at(x, y):
    """True if the desktop itself (not an app window) is under this physical screen point."""
    hwnd = _user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return False
    root = _user32.GetAncestor(hwnd, _GA_ROOT) or hwnd
    class_name = ctypes.create_unicode_buffer(64)
    _user32.GetClassNameW(root, class_name, len(class_name))
    return class_name.value in DESKTOP_CLASSES


def foreground_is_fullscreen():
    """True while a full-screen app (usually a game or video) is the active window."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return False
    class_name = ctypes.create_unicode_buffer(64)
    _user32.GetClassNameW(hwnd, class_name, len(class_name))
    if class_name.value in DESKTOP_CLASSES or class_name.value in TASKBAR_CLASSES:
        return False
    left, top, right, bottom = _frame_bounds(hwnd)
    monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST))
    m_left, m_top, m_right, m_bottom = monitor["Monitor"]
    return left <= m_left and top <= m_top and right >= m_right and bottom >= m_bottom


def _is_showing(hwnd):
    """Visible, not minimized, and not secretly hidden by Windows."""
    if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
        return False
    cloaked = wintypes.DWORD()
    _dwmapi.DwmGetWindowAttribute(hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return not cloaked.value


def _role_of(hwnd, class_name):
    """What a window means for the snow, or None if the snow should ignore it."""
    _user32.GetClassNameW(hwnd, class_name, len(class_name))
    name = class_name.value
    if name in TASKBAR_CLASSES:
        return ROLE_TASKBAR
    ex_style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & 0xFFFFFFFF
    if ex_style & win32con.WS_EX_TRANSPARENT:
        return None  # click-through overlays (game overlays, Snowcat itself) aren't really "there"
    if name in SHELL_POPUP_CLASSES:
        return ROLE_BLOCKER
    if ex_style & win32con.WS_EX_TOOLWINDOW:
        return None  # floating helpers and desktop widgets
    if not _user32.GetWindowTextLengthW(hwnd):
        return None  # untitled helper windows
    if ex_style & win32con.WS_EX_LAYERED and _fully_transparent(hwnd):
        return None
    return ROLE_WINDOW


def _fully_transparent(hwnd):
    """True for a layered window that has been faded all the way out."""
    alpha = ctypes.c_ubyte()
    flags = wintypes.DWORD()
    ok = _user32.GetLayeredWindowAttributes(hwnd, None, ctypes.byref(alpha), ctypes.byref(flags))
    return bool(ok) and bool(flags.value & _LWA_ALPHA) and alpha.value == 0


def _frame_bounds(hwnd):
    """The window's visible box (left, top, right, bottom) in physical pixels."""
    rect = wintypes.RECT()
    result = _dwmapi.DwmGetWindowAttribute(
        hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
    if result != 0:
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom
