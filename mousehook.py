"""
Right-click drags anywhere become snowball slingshot pulls.

A low-level mouse hook sees the right button before any app does. When you
press it, Snowcat holds the press back for a moment:
- drag more than a few pixels and it becomes a slingshot pull; the app
  underneath never sees the click, so no right-click menu pops up;
- let go without dragging and Snowcat hands the app a normal right-click,
  so right-click menus still work as usual.

It steps aside completely (the app gets the button straight away) whenever
should_catch() says no, e.g. in full-screen games where the right button
means "aim".
"""

import ctypes
import math
from ctypes import wintypes

from PyQt6.QtCore import QTimer

DRAG_START = 8  # px the mouse must move with the button held before it counts as a drag

_WH_MOUSE_LL = 14
_WM_MOUSEMOVE = 0x0200
_WM_RBUTTONDOWN = 0x0204
_WM_RBUTTONUP = 0x0205
_LLMHF_INJECTED = 0x1
_INPUT_MOUSE = 0
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010

_IDLE, _WAITING, _DRAGGING, _PASSING = range(4)


class _MouseHookInfo(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("padding", ctypes.c_byte * 32)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _InputUnion)]


_HookProc = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user32 = ctypes.WinDLL("user32")
_kernel32 = ctypes.WinDLL("kernel32")
_user32.SetWindowsHookExW.argtypes = (ctypes.c_int, _HookProc, wintypes.HINSTANCE, wintypes.DWORD)
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user32.CallNextHookEx.restype = wintypes.LPARAM
_user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int)
_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class RightDragCatcher:
    """Watches the right mouse button. Read `anchor` (where a drag started) and call take_release()."""

    def __init__(self, should_catch):
        self._should_catch = should_catch  # should_catch(x, y) -> bool, asked on each right press
        self._state = _IDLE
        self._press = None
        self._released = False
        self.anchor = None  # physical screen point where the current drag started, or None
        self._proc = _HookProc(self._on_mouse)  # keep a reference so it isn't garbage collected
        self._hook = None

    def start(self):
        """Install the hook. Returns False if Windows refused (the slingshot then needs the desktop)."""
        self._hook = _user32.SetWindowsHookExW(_WH_MOUSE_LL, self._proc, _kernel32.GetModuleHandleW(None), 0)
        return bool(self._hook)

    def stop(self):
        if self._hook:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def take_release(self):
        """True once, right after a right-drag ends."""
        released, self._released = self._released, False
        return released

    def _on_mouse(self, code, message, data):
        try:
            if code >= 0 and self._handle(message, _MouseHookInfo.from_address(data)):
                return 1  # swallow: the app underneath never sees it
        except Exception:  # never let an error break the mouse
            self._state = _IDLE
        return _user32.CallNextHookEx(self._hook, code, message, data)

    def _handle(self, message, info):
        """Returns True to swallow this mouse event."""
        if info.flags & _LLMHF_INJECTED:
            return False  # our own replayed clicks (and other software's) go straight through
        x, y = info.pt.x, info.pt.y

        if message == _WM_RBUTTONDOWN:
            if self._state == _IDLE and self._should_catch(x, y):
                self._state, self._press = _WAITING, (x, y)
                return True
            self._state = _PASSING
            return False

        if message == _WM_MOUSEMOVE and self._state == _WAITING:
            if math.dist((x, y), self._press) >= DRAG_START:
                self._state = _DRAGGING
                self.anchor = self._press
            return False

        if message == _WM_RBUTTONUP:
            state, self._state = self._state, _IDLE
            if state == _DRAGGING:
                self.anchor = None
                self._released = True
                return True
            if state == _WAITING:
                QTimer.singleShot(0, _replay_right_click)  # just a click: give it to the app after all
                return True
        return False


def _replay_right_click():
    inputs = (_Input * 2)()
    for item, flag in zip(inputs, (_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP)):
        item.type = _INPUT_MOUSE
        item.u.mi.dwFlags = flag
    _user32.SendInput(2, inputs, ctypes.sizeof(_Input))
