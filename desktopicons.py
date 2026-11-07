"""
Where the shortcut icons on the desktop are, so snow can settle on them.

The icons live inside Explorer's desktop list, so reading their positions
means asking Explorer through a little shared memory. That takes a few
milliseconds for a full desktop, so it happens on a background thread about
once a second and the snow just uses the latest answer.
"""

import ctypes
import threading
from ctypes import wintypes

POLL_SECONDS = 1.0
MAX_ICONS = 300
REPLY_TIMEOUT_MS = 100   # never wait long on a busy Explorer
ICON_INSET = 3           # px; icon pictures have a little empty margin at the top

_LVM_GETITEMCOUNT = 0x1004
_LVM_GETITEMRECT = 0x100E
_LVIR_ICON = 1
_SMTO_ABORTIFHUNG = 0x2
_PROCESS_ACCESS = 0x0008 | 0x0010 | 0x0020  # VM operation, read, write
_MEM_COMMIT_RESERVE = 0x3000
_MEM_RELEASE = 0x8000
_PAGE_READWRITE = 0x04

_user32 = ctypes.WinDLL("user32")
_kernel32 = ctypes.WinDLL("kernel32")
_user32.FindWindowExW.argtypes = (wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
_user32.FindWindowExW.restype = wintypes.HWND
_user32.IsWindowVisible.argtypes = (wintypes.HWND,)
_user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
_user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_user32.SendMessageTimeoutW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
_user32.SendMessageTimeoutW.restype = wintypes.LPARAM
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.VirtualAllocEx.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD)
_kernel32.VirtualAllocEx.restype = ctypes.c_void_p
_kernel32.VirtualFreeEx.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD)
_kernel32.WriteProcessMemory.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p)
_kernel32.ReadProcessMemory.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p)


class IconWatcher:
    """Keeps an up-to-date list of the desktop icons' picture boxes (physical px)."""

    def __init__(self):
        self.icons = []  # [(left, top, right, bottom), ...]; replaced whole, so safe to read any time
        self.enabled = True
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="desktop icons", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.icons = desktop_icon_boxes() if self.enabled else []
            except OSError:
                self.icons = []
            self._stop.wait(POLL_SECONDS)


def desktop_icon_boxes():
    """The picture part of every desktop icon, or [] if they're hidden or can't be read."""
    view = _desktop_list_view()
    if not view or not _user32.IsWindowVisible(view):
        return []
    count = _send(view, _LVM_GETITEMCOUNT, 0, 0)
    if not count:
        return []

    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(view, ctypes.byref(pid))
    process = _kernel32.OpenProcess(_PROCESS_ACCESS, False, pid.value)
    if not process:
        return []
    rect = wintypes.RECT()
    remote = _kernel32.VirtualAllocEx(process, None, ctypes.sizeof(rect), _MEM_COMMIT_RESERVE, _PAGE_READWRITE)
    if not remote:
        _kernel32.CloseHandle(process)
        return []
    try:
        origin = wintypes.POINT()
        _user32.ClientToScreen(view, ctypes.byref(origin))
        boxes = []
        for i in range(min(count, MAX_ICONS)):
            rect.left, rect.top, rect.right, rect.bottom = _LVIR_ICON, 0, 0, 0
            _kernel32.WriteProcessMemory(process, remote, ctypes.byref(rect), ctypes.sizeof(rect), None)
            if not _send(view, _LVM_GETITEMRECT, i, remote):
                continue
            _kernel32.ReadProcessMemory(process, remote, ctypes.byref(rect), ctypes.sizeof(rect), None)
            boxes.append(_picture_box(rect, origin))
        return boxes
    finally:
        _kernel32.VirtualFreeEx(process, remote, 0, _MEM_RELEASE)
        _kernel32.CloseHandle(process)


def _picture_box(rect, origin):
    """The icon's square picture, centred in the space Explorer reserves for it."""
    width, height = rect.right - rect.left, rect.bottom - rect.top
    size = max(8, min(width, height - 4))
    left = origin.x + rect.left + (width - size) / 2
    top = origin.y + rect.top + (height - size) / 2
    return left + ICON_INSET, top + ICON_INSET, left + size - ICON_INSET, top + size


def _desktop_list_view():
    """Explorer's list of desktop icons. It sits under Progman, or under a WorkerW on some setups."""
    for parent_class in ("Progman", "WorkerW"):
        parent = None
        while True:
            parent = _user32.FindWindowExW(None, parent, parent_class, None)
            if not parent:
                break
            shell_view = _user32.FindWindowExW(parent, None, "SHELLDLL_DefView", None)
            if shell_view:
                return _user32.FindWindowExW(shell_view, None, "SysListView32", None)
    return None


def _send(hwnd, message, wparam, lparam):
    result = ctypes.c_size_t()
    ok = _user32.SendMessageTimeoutW(hwnd, message, wparam, lparam or 0,
                                     _SMTO_ABORTIFHUNG, REPLY_TIMEOUT_MS, ctypes.byref(result))
    return result.value if ok else 0
