# -*- coding: utf-8 -*-
"""
gpw_battery.py —— 罗技 GPW（G PRO Wireless 一代）电量托盘小工具

特点：
  * 纯 ctypes 调用 Win32，无第三方依赖（只需要 Python 3.9+）
  * 托盘图标实时显示电量（电池图标 + 颜色分级）
  * 鼠标悬停弹出提示窗，样式仿 Windows 11 原生 tooltip（深色圆角卡片）
  * 弹窗固定在任务栏上方、不遮挡任务栏；始终置顶、不抢焦点、不出现在 Alt+Tab

运行：
    pythonw gpw_battery.py        # 无控制台窗口
    python  gpw_battery.py --once # 命令行读取一次电量
    python  gpw_battery.py --demo # 用假数据预览弹窗样式（调试用）
"""

import ctypes
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes

import hidpp

# ===================================================================== 常量
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
WM_APP = 0x8000
WM_CONTEXTMENU = 0x007B
NIN_SELECT = 0x0400
NIN_POPUPOPEN = 0x0406
NIN_POPUPCLOSE = 0x0407

WM_TRAY = WM_APP + 1          # 托盘回调消息
WM_REFRESH_DONE = WM_APP + 2  # 后台线程读完后通知 UI
WM_MENU_CMD = 0x8003

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIM_SETVERSION = 0x00000004
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NOTIFYICON_VERSION_4 = 4

TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008
MF_GRAYED = 0x00000001

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0

DT_LEFT = 0x0000
DT_SINGLELINE = 0x0020
DT_NOPREFIX = 0x0800
DT_CALCRECT = 0x0400
TRANSPARENT = 1
ANTIALIASED_QUALITY = 4
DEFAULT_CHARSET = 1
FW_NORMAL = 400
FW_SEMIBOLD = 600

SM_CXSMICON = 49
SM_CYSMICON = 50
MONITOR_DEFAULTTONEAREST = 2

IDI_APPLICATION = 32512

# 配色（仿 Win11 深色 tooltip）
CLR_BG = (43, 43, 43)
CLR_BORDER = (62, 62, 62)
CLR_TITLE = (255, 255, 255)
CLR_SUB = (206, 206, 206)
CLR_TRACK = (74, 74, 74)
CLR_OK = (76, 199, 106)
CLR_MID = (240, 169, 59)
CLR_LOW = (229, 87, 74)
CLR_CHARGE = (76, 159, 232)
CLR_UNKNOWN = (140, 140, 140)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


# ===================================================================== 结构体
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID),
                ("hBalloonIcon", wintypes.HICON)]


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("guidItem", GUID)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


# ===================================================================== API 原型
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.SetTimer.restype = wintypes.UINT
user32.SetTimer.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.PtInRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.POINT]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                       ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                       ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
                                       ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.restype = wintypes.BOOL
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.MonitorFromRect.restype = wintypes.HANDLE
user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.LoadIconW.restype = wintypes.HICON
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.DrawTextW.restype = ctypes.c_int
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                             ctypes.POINTER(wintypes.RECT), wintypes.UINT]
user32.GetDpiForSystem.restype = wintypes.UINT
user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.LoadCursorW.restype = ctypes.c_void_p
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]

kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

gdi32.MoveToEx.restype = wintypes.BOOL
gdi32.MoveToEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                           ctypes.POINTER(wintypes.POINT)]
gdi32.LineTo.restype = wintypes.BOOL
gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]

shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconGetRect.restype = ctypes.c_long
shell32.Shell_NotifyIconGetRect.argtypes = [ctypes.POINTER(NOTIFYICONIDENTIFIER),
                                            ctypes.POINTER(wintypes.RECT)]

gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE,
                                   wintypes.DWORD]
gdi32.CreateBitmap.restype = wintypes.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT,
                               ctypes.c_void_p]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreatePen.restype = wintypes.HPEN
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
gdi32.CreateFontW.restype = wintypes.HFONT
gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                              wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                              wintypes.DWORD, wintypes.LPCWSTR]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetStockObject.restype = wintypes.HGDIOBJ
gdi32.GetStockObject.argtypes = [ctypes.c_int]
user32.DrawIconEx.restype = wintypes.BOOL
user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HANDLE,
                              wintypes.UINT]

NULL_BRUSH = 5
gdi32.SetBkMode.restype = ctypes.c_int
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetTextColor.restype = wintypes.COLORREF
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.RoundRect.restype = wintypes.BOOL
gdi32.RoundRect.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int, ctypes.c_int]
user32.CreateIconIndirect.restype = wintypes.HICON
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
gdi32.GdiFlush.restype = wintypes.BOOL


def RGB(r, g, b):
    return r | (g << 8) | (b << 16)


# ===================================================================== 图标绘制
def make_battery_icon(percent, charging=False, size=None, connected=True):
    """把电池图形画到位图里，返回 HICON（调用方负责 DestroyIcon）"""
    if size is None:
        size = max(16, user32.GetSystemMetrics(SM_CXSMICON))
    hdc_screen = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    bits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                 ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(mem_dc, hbm)
    try:
        if not connected:
            color = CLR_UNKNOWN
            level = 0
        elif charging:
            color = CLR_CHARGE
            level = percent if percent is not None else 0
        else:
            p = percent or 0
            color = CLR_OK if p > 50 else (CLR_MID if p > 20 else CLR_LOW)
            level = p

        s = size / 32.0

        def S(v):
            return int(round(v * s))

        # 32x32 设计稿坐标
        BODY = (S(2), S(9), S(26), S(25))     # 电池外壳
        NUB = (S(26), S(14), S(30), S(20))    # 正极触点
        INNER = (S(5), S(12), S(23), S(22))   # 内部可填充区域

        # 电池外壳（空心，深浅色任务栏都清晰）
        pen = gdi32.CreatePen(0, max(1, S(2)), RGB(*color))
        old_pen = gdi32.SelectObject(mem_dc, pen)
        hollow = gdi32.GetStockObject(NULL_BRUSH)
        old_brush = gdi32.SelectObject(mem_dc, hollow)
        gdi32.RoundRect(mem_dc, BODY[0], BODY[1], BODY[2], BODY[3], S(3), S(3))

        # 正极触点
        brush = gdi32.CreateSolidBrush(RGB(*color))
        gdi32.SelectObject(mem_dc, brush)
        gdi32.RoundRect(mem_dc, NUB[0], NUB[1], NUB[2], NUB[3], S(2), S(2))

        # 电量填充
        if connected and level > 0:
            inner_w = INNER[2] - INNER[0]
            fill_w = max(1, int(round(inner_w * min(100, max(0, level)) / 100.0)))
            gdi32.SelectObject(mem_dc, brush)
            gdi32.RoundRect(mem_dc, INNER[0], INNER[1], INNER[0] + fill_w, INNER[3],
                            S(2), S(2))
        elif not connected:
            # 断线：画一道斜杠
            gdi32.SelectObject(mem_dc, pen)
            gdi32.MoveToEx(mem_dc, S(6), S(21), None)
            gdi32.LineTo(mem_dc, S(22), S(11))

        gdi32.SelectObject(mem_dc, old_pen)
        gdi32.SelectObject(mem_dc, old_brush)
        gdi32.DeleteObject(brush)
        gdi32.DeleteObject(pen)
        gdi32.GdiFlush()

        # 关键：GDI 不写 alpha 通道，把画过的像素 alpha 置为不透明
        buf = ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte * (size * size * 4))).contents
        for i in range(size * size):
            o = i * 4
            if buf[o] or buf[o + 1] or buf[o + 2]:
                buf[o + 3] = 255

        # AND 掩码全 0（透明度交给 alpha 通道）
        stride = ((size + 15) // 16) * 2
        zero_mask = ctypes.create_string_buffer(stride * size)
        mask = gdi32.CreateBitmap(size, size, 1, 1, zero_mask)
        ii = ICONINFO()
        ii.fIcon = True
        ii.hbmMask = mask
        ii.hbmColor = hbm
        hicon = user32.CreateIconIndirect(ctypes.byref(ii))
        gdi32.DeleteObject(mask)
        return hicon
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, hdc_screen)


# ===================================================================== 圆角遮罩
_ALPHA_CACHE = {}


def _rounded_alpha(w, h, radius, supersample=4):
    """返回 w*h 的覆盖率字节串（0..255），用于平滑圆角（带缓存）"""
    key = (w, h, radius, supersample)
    if key in _ALPHA_CACHE:
        return _ALPHA_CACHE[key]
    cov = bytearray(w * h)
    r = max(1, min(radius, w // 2, h // 2))
    inv = 1.0 / (supersample * supersample)

    def inside(px, py):
        if px < 0 or py < 0 or px > w or py > h:
            return False
        if r <= px <= w - r or r <= py <= h - r:
            return True
        cx = r if px < r else w - r
        cy = r if py < r else h - r
        dx, dy = px - cx, py - cy
        return dx * dx + dy * dy <= r * r

    for y in range(h):
        for x in range(w):
            # 只在靠近边缘的像素上做超采样
            if r <= x <= w - r - 1 and r <= y <= h - r - 1:
                cov[y * w + x] = 255
                continue
            if not (0 <= x < w and 0 <= y < h):
                continue
            hit = 0
            for j in range(supersample):
                for i in range(supersample):
                    if inside(x + (i + 0.5) / supersample, y + (j + 0.5) / supersample):
                        hit += 1
            cov[y * w + x] = int(round(255 * hit * inv))
    _ALPHA_CACHE[key] = cov
    return cov


# ===================================================================== 弹窗
class Popup:
    """仿 Win11 深色 tooltip 的无边框置顶弹窗（分层窗口 + 逐像素透明）"""

    CLASS_NAME = "GPWBatteryPopup"

    def __init__(self, app):
        self.app = app
        self.hwnd = None
        self.visible = False
        self.rect = wintypes.RECT(0, 0, 0, 0)
        self._wndproc_ref = None
        self._dpi = 96

    # -- 创建 ------------------------------------------------------
    def create(self):
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wnd_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))
        wc.lpszClassName = self.CLASS_NAME
        user32.RegisterClassExW(ctypes.byref(wc))
        ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        self.hwnd = user32.CreateWindowExW(ex, self.CLASS_NAME, "GPW Battery",
                                           WS_POPUP, 0, 0, 10, 10,
                                           None, None, hinst, None)
        return self.hwnd

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_PAINT:
            # 内容全部由 UpdateLayeredWindow 绘制
            return 0
        if msg == WM_LBUTTONUP:
            self.app.refresh(force=True)
            return 0
        if msg == WM_DESTROY:
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -- 绘制 ------------------------------------------------------
    def _scaled(self, v):
        return int(round(v * self._dpi / 96.0))

    def render(self, reading, dpi, paint=True):
        """按当前数据重绘并更新分层窗口，返回窗口尺寸 (w,h)"""
        self._dpi = dpi
        if reading is None:
            title = "GPW1"
            sub = "正在读取…"
            level = None
            charging = False
            connected = True
        else:
            title = reading.device_name or "GPW1"
            if reading.error:
                err = reading.error
                state = getattr(reading, "state", "")
                if state == "asleep":
                    sub = "鼠标休眠 · 移动鼠标唤醒"
                elif state == "no_receiver":
                    sub = "接收器无响应 · 请重新插拔"
                elif "未连接" in err or state == "absent":
                    sub = "鼠标未连接 · 请打开电源"
                else:
                    sub = "未检测到设备"
                level = None
                charging = False
                connected = False
            else:
                level = reading.percent
                charging = reading.charging
                sub = f"电量 {level}%  ·  {reading.status_text}" if level is not None else "电量未知"
                connected = True

        f_title = gdi32.CreateFontW(-self._scaled(15), 0, 0, 0, FW_SEMIBOLD, 0, 0, 0,
                                    DEFAULT_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0, "Segoe UI")
        f_sub = gdi32.CreateFontW(-self._scaled(13), 0, 0, 0, FW_NORMAL, 0, 0, 0,
                                  DEFAULT_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0, "Segoe UI")

        hdc_screen = user32.GetDC(None)
        tmp = gdi32.CreateCompatibleDC(hdc_screen)
        pad_x, pad_y = self._scaled(16), self._scaled(13)
        gap1, gap2 = self._scaled(3), self._scaled(9)
        bar_h = max(2, self._scaled(3))
        radius = self._scaled(8)

        tw = self._measure(tmp, f_title, title)
        sw = self._measure(tmp, f_sub, sub)
        title_h = self._scaled(20)
        sub_h = self._scaled(18)
        w = max(tw, sw, self._scaled(132)) + pad_x * 2
        h = pad_y * 2 + title_h + gap1 + sub_h + gap2 + bar_h

        if not paint:  # 只量尺寸
            gdi32.DeleteObject(f_title)
            gdi32.DeleteObject(f_sub)
            gdi32.DeleteDC(tmp)
            user32.ReleaseDC(None, hdc_screen)
            return w, h

        # 建 DIB
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        hbm = gdi32.CreateDIBSection(tmp, ctypes.byref(bmi), DIB_RGB_COLORS,
                                     ctypes.byref(bits), None, 0)
        old_bmp = gdi32.SelectObject(tmp, hbm)

        # 背景
        bg = gdi32.CreateSolidBrush(RGB(*CLR_BG))
        full = wintypes.RECT(0, 0, w, h)
        user32.FillRect(tmp, ctypes.byref(full), bg)
        gdi32.DeleteObject(bg)

        # 细边框（1px，让深色卡片在深色背景上有轮廓）
        pen = gdi32.CreatePen(0, 1, RGB(*CLR_BORDER))
        old_pen = gdi32.SelectObject(tmp, pen)
        hollow = gdi32.CreateSolidBrush(RGB(*CLR_BG))
        old_brush = gdi32.SelectObject(tmp, hollow)
        gdi32.RoundRect(tmp, 0, 0, w, h, radius * 2, radius * 2)
        gdi32.SelectObject(tmp, old_pen)
        gdi32.SelectObject(tmp, old_brush)
        gdi32.DeleteObject(pen)
        gdi32.DeleteObject(hollow)

        gdi32.SetBkMode(tmp, TRANSPARENT)

        # 标题
        gdi32.SelectObject(tmp, f_title)
        gdi32.SetTextColor(tmp, RGB(*CLR_TITLE))
        rc = wintypes.RECT(pad_x, pad_y, w - pad_x, pad_y + title_h)
        user32.DrawTextW(tmp, title, -1, ctypes.byref(rc),
                         DT_LEFT | DT_SINGLELINE | DT_NOPREFIX)

        # 副标题
        gdi32.SelectObject(tmp, f_sub)
        gdi32.SetTextColor(tmp, RGB(*CLR_SUB))
        rc = wintypes.RECT(pad_x, pad_y + title_h + gap1, w - pad_x,
                           pad_y + title_h + gap1 + sub_h)
        user32.DrawTextW(tmp, sub, -1, ctypes.byref(rc),
                         DT_LEFT | DT_SINGLELINE | DT_NOPREFIX)

        # 电量条
        bar_x0, bar_y0 = pad_x, h - pad_y - bar_h
        bar_x1 = w - pad_x
        track = gdi32.CreateSolidBrush(RGB(*CLR_TRACK))
        old_b = gdi32.SelectObject(tmp, track)
        gdi32.RoundRect(tmp, bar_x0, bar_y0, bar_x1, bar_y0 + bar_h, bar_h, bar_h)
        gdi32.SelectObject(tmp, old_b)
        gdi32.DeleteObject(track)
        if connected and level:
            if charging:
                color = CLR_CHARGE
            else:
                color = CLR_OK if level > 50 else (CLR_MID if level > 20 else CLR_LOW)
            fill = gdi32.CreateSolidBrush(RGB(*color))
            old_b = gdi32.SelectObject(tmp, fill)
            fw = bar_x0 + max(bar_h, int(round((bar_x1 - bar_x0) * min(100, level) / 100.0)))
            gdi32.RoundRect(tmp, bar_x0, bar_y0, fw, bar_y0 + bar_h, bar_h, bar_h)
            gdi32.SelectObject(tmp, old_b)
            gdi32.DeleteObject(fill)

        gdi32.GdiFlush()

        # 逐像素圆角 alpha
        cov = _rounded_alpha(w, h, radius)
        buf = ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte * (w * h * 4))).contents
        for idx in range(w * h):
            a = cov[idx]
            o = idx * 4
            if a == 255:
                buf[o + 3] = 255
            elif a == 0:
                buf[o] = buf[o + 1] = buf[o + 2] = buf[o + 3] = 0
            else:
                buf[o] = buf[o] * a // 255
                buf[o + 1] = buf[o + 1] * a // 255
                buf[o + 2] = buf[o + 2] * a // 255
                buf[o + 3] = a

        # 更新分层窗口
        dst = wintypes.POINT(self.rect.left, self.rect.top)
        src = wintypes.POINT(0, 0)
        size = wintypes.SIZE(w, h)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.hwnd, hdc_screen, ctypes.byref(dst),
                                   ctypes.byref(size), tmp, ctypes.byref(src), 0,
                                   ctypes.byref(blend), ULW_ALPHA)

        gdi32.SelectObject(tmp, old_bmp)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(tmp)
        user32.ReleaseDC(None, hdc_screen)
        gdi32.DeleteObject(f_title)
        gdi32.DeleteObject(f_sub)
        return w, h

    @staticmethod
    def _measure(dc, font, text):
        old = gdi32.SelectObject(dc, font)
        rc = wintypes.RECT(0, 0, 0, 0)
        user32.DrawTextW(dc, text, -1, ctypes.byref(rc),
                         DT_LEFT | DT_SINGLELINE | DT_NOPREFIX | DT_CALCRECT)
        gdi32.SelectObject(dc, old)
        return rc.right - rc.left

    # -- 显示 / 隐藏 -----------------------------------------------
    def show_at(self, anchor, reading, dpi, align="center"):
        """anchor 为托盘图标屏幕矩形，弹窗显示在它上方（不压任务栏）"""
        # 先量尺寸
        w, h = self.render(reading, dpi, paint=False)

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        hmon = user32.MonitorFromRect(ctypes.byref(anchor), MONITOR_DEFAULTTONEAREST)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        work = mi.rcWork

        if align == "right":
            x = anchor.right - w
        else:
            x = (anchor.left + anchor.right) // 2 - w // 2
        gap = self._scaled(6)
        # 任务栏在下方：图标顶部即任务栏上沿附近，向上弹出
        y = min(anchor.top, work.bottom) - h - gap
        if y < work.top + 4:  # 任务栏在上方 / 垂直任务栏
            y = max(work.top + 4, min(anchor.bottom + gap, work.bottom - h - 4))
        x = max(work.left + 4, min(x, work.right - w - 4))
        y = max(work.top + 4, min(y, work.bottom - h - 4))

        self.rect = wintypes.RECT(x, y, x + w, y + h)
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, w, h,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW)
        # 位置确定后再画一次，保证 UpdateLayeredWindow 使用正确坐标
        self.render(reading, dpi)
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.visible = True

    def refresh_content(self, reading, dpi):
        if self.visible:
            self.render(reading, dpi)

    def hide(self):
        if self.visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False

    def contains(self, pt):
        if not self.visible:
            return False
        return (self.rect.left <= pt.x < self.rect.right and
                self.rect.top <= pt.y < self.rect.bottom)


# ===================================================================== 主程序
class App:
    ID_TRAY = 1
    ID_TIMER_HOVER = 1
    ID_TIMER_REFRESH = 2
    MENU_REFRESH = 1001
    MENU_AUTOSTART = 1002
    MENU_EXIT = 1003

    def __init__(self, demo=False):
        self.demo = demo
        self.hwnd = None
        self.hicon = None
        self.popup = None
        self.reading = None
        self.last_ok_time = 0.0
        self._lock = threading.Lock()
        self._monitor = None
        self._stop = threading.Event()
        self._wndproc_ref = None
        self._away_ticks = 0
        self._icon_rect = wintypes.RECT(0, 0, 0, 0)
        self._icon_rect_time = 0.0
        self._icon_fallback = False
        self._popup_shown_at = 0.0
        self._hover_since = 0.0
        self._pending_popup = None
        self._wm_taskbar_created = 0
        self._pending_refresh = False
        self.preview_lock = False
        dpi = user32.GetDpiForSystem()
        self.dpi = dpi if dpi else 96
        if demo:
            self.reading = hidpp.BatteryReading(percent=85, status=0, voltage=3920,
                                                device_name="G PRO Wireless",
                                                transport="接收器", source="demo")
            self.last_ok_time = time.time()

    # -- 初始化 ----------------------------------------------------
    def create(self):
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wnd_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = "GPWBatteryTray"
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err not in (1410,):  # 类已注册
                raise OSError(f"RegisterClassEx 失败: {err}")
        self.hwnd = user32.CreateWindowExW(0, "GPWBatteryTray", "GPW Battery",
                                           0, 0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            raise OSError("创建消息窗口失败")
        # Explorer 重启后会广播 TaskbarCreated，收到就重新挂上托盘图标
        self._wm_taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self.popup = Popup(self)
        self.popup.create()
        self._add_tray_icon()
        user32.SetTimer(self.hwnd, self.ID_TIMER_HOVER, 60, None)
        user32.SetTimer(self.hwnd, self.ID_TIMER_REFRESH, 1000, None)
        self._start_monitor()
        return self

    # -- 托盘 ------------------------------------------------------
    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = self.ID_TRAY
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = ""  # 空提示：避免和自绘弹窗重复
        return nid

    def _add_tray_icon(self, attempts=24, delay=0.5):
        """
        添加托盘图标。
        开机自启时 Explorer 的任务栏/托盘区往往还没初始化完，
        Shell_NotifyIcon(NIM_ADD) 会返回 E_FAIL(0x80004005)，这里退避重试。
        """
        self._update_icon()
        last_err = 0
        for i in range(attempts):
            nid = self._nid()
            if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                nid.uVersion = NOTIFYICON_VERSION_4
                shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
                return True
            last_err = ctypes.get_last_error()
            time.sleep(delay if i < 6 else 1.0)
        raise OSError(f"添加托盘图标失败: {last_err} (0x{last_err & 0xFFFFFFFF:08X})")

    def _update_icon(self):
        r = self.reading
        percent = None if (r is None or r.error) else r.percent
        charging = bool(r and not r.error and r.charging)
        connected = not (r is not None and r.error)
        new = make_battery_icon(percent, charging, connected=connected)
        if new:
            old = self.hicon
            self.hicon = new
            if self.hwnd:
                nid = self._nid()
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
            if old:
                user32.DestroyIcon(old)

    def _remove_tray_icon(self):
        nid = self._nid()
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        if self.hicon:
            user32.DestroyIcon(self.hicon)
            self.hicon = None

    def icon_rect(self, max_age=0.5):
        """
        托盘图标屏幕矩形。
        Windows 11 把新图标放进「隐藏的图标」时，Shell_NotifyIconGetRect 会返回越界
        的无效坐标，这里做合法性校验，无效则退化为「通知区域右上角」。
        """
        if self._icon_rect_time and time.time() - self._icon_rect_time < max_age:
            return self._icon_rect
        self._icon_rect_time = time.time()
        ident = NOTIFYICONIDENTIFIER()
        ident.cbSize = ctypes.sizeof(NOTIFYICONIDENTIFIER)
        ident.hWnd = self.hwnd
        ident.uID = self.ID_TRAY
        rc = wintypes.RECT()
        hr = shell32.Shell_NotifyIconGetRect(ctypes.byref(ident), ctypes.byref(rc))
        vx = user32.GetSystemMetrics(76)
        vy = user32.GetSystemMetrics(77)
        vw = user32.GetSystemMetrics(78)
        vh = user32.GetSystemMetrics(79)
        ok = (hr == 0 and rc.right > rc.left and rc.bottom > rc.top and
              rc.left >= vx and rc.right <= vx + vw and
              rc.top >= vy and rc.bottom <= vy + vh)
        if ok:
            self._icon_rect = rc
            self._icon_fallback = False
            return rc

        # 回退：贴住任务栏右下角（通知区域右侧）
        tray = user32.FindWindowW("Shell_TrayWnd", None)
        trc = wintypes.RECT()
        if tray and user32.GetWindowRect(tray, ctypes.byref(trc)) and trc.right > trc.left:
            m = int(round(14 * self.dpi / 96.0))
            size = max(16, user32.GetSystemMetrics(SM_CXSMICON))
            rc = wintypes.RECT(trc.right - m - size, trc.bottom - m - size,
                               trc.right - m, trc.bottom - m)
            self._icon_rect = rc
            self._icon_fallback = True
            return rc
        return None

    # -- 菜单 ------------------------------------------------------
    def _show_menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, self.MENU_REFRESH, "刷新电量")
        checked = MF_CHECKED if self._autostart_enabled() else 0
        user32.AppendMenuW(menu, MF_STRING | checked, self.MENU_AUTOSTART, "开机自启动")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, self.MENU_EXIT, "退出")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN, pt.x, pt.y, 0,
                              self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)

    # -- 开机自启 --------------------------------------------------
    # 注意：这里刻意不使用「启动文件夹 + PowerShell 创建快捷方式」的老做法。
    # 那种写法会 fork 出 powershell.exe 去写启动项，行为上非常像恶意软件的
    # 持久化（T1059 + T1547），卡巴斯基会直接把宿主程序删掉。
    # 改用 HKCU\...\Run 注册表值，由进程自己写入，无子进程、无脚本。
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    RUN_VALUE = "GPWBattery"

    @staticmethod
    def _autostart_command():
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pyw):
            pyw = sys.executable
        return f'"{pyw}" "{os.path.abspath(__file__)}"'

    def _autostart_enabled(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY) as k:
                val, _ = winreg.QueryValueEx(k, self.RUN_VALUE)
                return bool(val)
        except OSError:
            return False

    def _toggle_autostart(self):
        import winreg
        try:
            if self._autostart_enabled():
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, self.RUN_VALUE)
            else:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0,
                                        winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, self.RUN_VALUE, 0, winreg.REG_SZ,
                                      self._autostart_command())
        except Exception as e:
            print("设置开机自启失败:", e, file=sys.stderr)

    # -- 数据轮询 --------------------------------------------------
    # 鼠标休眠时接收器不响应，若上次数值还很新，就保留旧值，避免图标在
    # 「彩色电量」和「灰色离线」之间来回跳
    STALE_KEEP_SECONDS = 60
    ASLEEP_KEEP_SECONDS = 3600

    def _store_reading(self, r):
        with self._lock:
            now = time.time()
            if r.percent is not None:
                self.reading = r
                self.last_ok_time = now
                return
            grace = self.ASLEEP_KEEP_SECONDS if getattr(r, "state", "") == "asleep" \
                else self.STALE_KEEP_SECONDS
            keep = (self.reading is not None and self.reading.percent is not None
                    and now - self.last_ok_time < grace)
            if not keep:
                self.reading = r

    def _start_monitor(self):
        def loop():
            while not self._stop.is_set():
                if self.demo:
                    time.sleep(2)
                    continue
                try:
                    r = hidpp.read_battery()
                except Exception as e:
                    r = hidpp.BatteryReading(error=f"读取异常: {e}")
                self._store_reading(r)
                if self.hwnd:
                    user32.PostMessageW(self.hwnd, WM_REFRESH_DONE, 0, 0)
                # 已连接 30s 一读；未连接 8s 重试一次
                self._stop.wait(30 if r.percent is not None else 8)

        self._monitor = threading.Thread(target=loop, name="battery-monitor", daemon=True)
        self._monitor.start()

    def refresh(self, force=False):
        """立刻重新读一次（弹窗显示时用）"""
        if self.demo or self._pending_refresh:
            return
        self._pending_refresh = True

        def work():
            try:
                r = hidpp.read_battery()
            except Exception as e:
                r = hidpp.BatteryReading(error=f"读取异常: {e}")
            self._store_reading(r)
            self._pending_refresh = False
            if self.hwnd:
                user32.PostMessageW(self.hwnd, WM_REFRESH_DONE, 0, 0)

        threading.Thread(target=work, daemon=True).start()

    # -- 悬停逻辑 --------------------------------------------------
    HOVER_DELAY = 0.5   # 鼠标停留多久才弹出（秒）

    def _on_hover_timer(self):
        if not self.hwnd or self.preview_lock:
            return
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        rc = self.icon_rect()
        # 图标在「隐藏的图标」里时坐标不可信，不参与悬停判定（改由系统悬停通知驱动）
        over_icon = (not self._icon_fallback) and bool(rc) and \
            user32.PtInRect(ctypes.byref(rc), pt)
        over_popup = self.popup.contains(pt)

        # 1) 图标可见：停留满 HOVER_DELAY 才弹出
        if over_icon and not self.popup.visible:
            if not self._hover_since:
                self._hover_since = time.time()
            elif time.time() - self._hover_since >= self.HOVER_DELAY:
                self._hover_since = 0.0
                self._show_popup()
                self._away_ticks = 0
            return
        if not over_icon:
            self._hover_since = 0.0

        # 2) 图标在隐藏区：系统悬停通知给出的待弹出任务
        if self._pending_popup is not None:
            deadline, anchor = self._pending_popup
            if self.popup.visible:
                self._pending_popup = None
            elif time.time() >= deadline:
                self._pending_popup = None
                self._show_popup(anchor=anchor)
                self._away_ticks = 0
            else:
                tol = self._scaled(24)
                if not (anchor.left - tol <= pt.x <= anchor.right + tol and
                        anchor.top - tol <= pt.y <= anchor.bottom + tol):
                    self._pending_popup = None   # 鼠标移开了，取消弹出

        # 3) 自动隐藏
        if not self.popup.visible:
            return
        if over_icon or over_popup:
            self._away_ticks = 0
            return
        # 刚弹出时给一点缓冲，避免鼠标还在图标上就被判定离开
        if time.time() - self._popup_shown_at < 0.8:
            return
        self._away_ticks += 1
        if self._away_ticks >= 3:  # ~360ms
            self.popup.hide()
            self._away_ticks = 0

    def _scaled(self, v):
        return int(round(v * self.dpi / 96.0))

    def _schedule_popup_at_cursor(self):
        """悬停通知到达：延时 HOVER_DELAY 后再弹出（锚点先记下来）"""
        if self.popup.visible:
            return
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        size = max(16, user32.GetSystemMetrics(SM_CXSMICON))
        anchor = wintypes.RECT(pt.x - size // 2, pt.y - size // 2,
                               pt.x + size // 2, pt.y + size // 2)
        self._pending_popup = (time.time() + self.HOVER_DELAY, anchor)

    def _show_popup(self, anchor=None, at_cursor=False):
        rc = anchor
        if rc is None:
            rc = self.icon_rect(max_age=0)
            if at_cursor or self._icon_fallback or not rc:
                # 用光标位置当锚点（图标在隐藏区域时最可靠）
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                size = max(16, user32.GetSystemMetrics(SM_CXSMICON))
                rc = wintypes.RECT(pt.x - size // 2, pt.y - size // 2,
                                   pt.x + size // 2, pt.y + size // 2)
        if not rc:
            return
        with self._lock:
            reading = self.reading
        self.popup.show_at(rc, reading, self.dpi, align="center")
        self._popup_shown_at = time.time()
        self._away_ticks = 0
        # 数据超过 10 秒则顺手刷新一次
        if not self.demo and (time.time() - self.last_ok_time > 10 or reading is None):
            self.refresh()

    def _on_popup_close(self):
        """系统通知鼠标已离开托盘图标"""
        if not self.popup.visible:
            return
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        if not self.popup.contains(pt):
            self.popup.hide()

    # -- 消息循环 --------------------------------------------------
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            if self._wm_taskbar_created and msg == self._wm_taskbar_created:
                # 资源管理器重启（或崩溃恢复）后，图标需要重新添加
                try:
                    self._add_tray_icon(attempts=12, delay=0.5)
                except Exception:
                    pass
                return 0
            if msg == WM_TRAY:
                evt = lparam & 0xFFFF
                if evt in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu()
                    return 0
                if evt in (NIN_POPUPOPEN,):
                    # 鼠标悬停到图标上（图标在隐藏区域时也能收到）→ 延时后弹出
                    self._schedule_popup_at_cursor()
                    return 0
                if evt in (NIN_POPUPCLOSE,):
                    self._pending_popup = None
                    self._on_popup_close()
                    return 0
                if evt in (WM_LBUTTONUP, NIN_SELECT, WM_LBUTTONDBLCLK):
                    # 点击是明确操作，立即弹出
                    self._pending_popup = None
                    self._hover_since = 0.0
                    if self.popup.visible:
                        self.popup.hide()
                    else:
                        self._show_popup(at_cursor=True)
                    return 0
                return 0
            if msg == WM_COMMAND:
                cmd = wparam & 0xFFFF
                if cmd == self.MENU_REFRESH:
                    self.refresh()
                elif cmd == self.MENU_AUTOSTART:
                    self._toggle_autostart()
                elif cmd == self.MENU_EXIT:
                    self.quit()
                return 0
            if msg == WM_TIMER:
                if wparam == self.ID_TIMER_HOVER:
                    self._on_hover_timer()
                elif wparam == self.ID_TIMER_REFRESH:
                    if self._pending_refresh is False and not self.demo:
                        with self._lock:
                            stale = (time.time() - self.last_ok_time > 30)
                        if stale:
                            self.refresh()
                return 0
            if msg == WM_REFRESH_DONE:
                self._update_icon()
                with self._lock:
                    reading = self.reading
                self.popup.refresh_content(reading, self.dpi)
                return 0
            if msg == WM_CLOSE or msg == WM_DESTROY:
                self.quit()
                return 0
        except Exception as e:
            print("wndproc 异常:", e, file=sys.stderr)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def quit(self):
        self._stop.set()
        if self.hwnd:
            user32.KillTimer(self.hwnd, self.ID_TIMER_HOVER)
            user32.KillTimer(self.hwnd, self.ID_TIMER_REFRESH)
            self._remove_tray_icon()
            self.hwnd_destroyed = True
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        user32.PostQuitMessage(0)

    def run(self):
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return 0


# ===================================================================== 入口
MUTEX_NAME = "GPWBattery_SingleInstance_v1"
ERROR_ALREADY_EXISTS = 183


def _acquire_single_instance():
    """已有实例在跑时直接退出，避免任务栏出现两个图标"""
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    h = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not h:
        return None
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return h


def _log_path():
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "GPWBattery-error.log")


def _log_exception(e):
    """写日志而不是弹 PyInstaller 的异常对话框（窗口模式下那框很吓人）"""
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + repr(e) + "\n")
            traceback.print_exc(file=f)
    except Exception:
        pass


def main(argv):
    if "--once" in argv:
        r = hidpp.read_battery(verbose=True)
        if r.percent is not None:
            print(f"{r.device_name}  电量 {r.percent}%  {r.status_text}  "
                  f"({r.voltage}mV, {r.transport}, {r.source})")
            return 0
        print("读取失败:", r.error)
        return 1

    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        pass

    if "--multi" not in argv and _acquire_single_instance() is None:
        return 0

    demo = "--demo" in argv
    try:
        app = App(demo=demo).create()
    except Exception as e:
        _log_exception(e)
        return 1
    if "--preview" in argv:
        # 直接显示弹窗并 15 秒后退出（用于截图检查样式）
        app.preview_lock = True
        app._show_popup()
        threading.Timer(15.0, lambda: user32.PostMessageW(app.hwnd, WM_COMMAND,
                                                           app.MENU_EXIT, 0)).start()
    try:
        return app.run()
    except Exception as e:
        _log_exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
