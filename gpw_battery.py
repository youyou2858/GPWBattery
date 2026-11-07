# -*- coding: utf-8 -*-
"""
gpw_battery.py —— 罗技 GPW（G PRO Wireless 一代）电量托盘小工具

特点：
  * 纯 ctypes 调用 Win32，无第三方依赖（只需要 Python 3.9+）
  * 托盘图标实时显示电量（电池图标 + 颜色分级）
  * 左键点击图标弹出提示窗，样式仿 Windows 11 原生 flyout（深色圆角卡片）
  * 弹窗以托盘图标为锚点、显示在图标上方，不遮挡任务栏
  * 右键菜单同样是同款深色圆角卡片（不是系统原生菜单）
  * 始终置顶、不抢焦点、不出现在 Alt+Tab；点空白处自动收起

运行：
    pythonw gpw_battery.py        # 无控制台窗口
    python  gpw_battery.py --once # 命令行读取一次电量
    python  gpw_battery.py --demo # 用假数据预览弹窗样式（调试用）
    python  gpw_battery.py --demo --preview       # 只弹左键弹窗，15 秒后退出
    python  gpw_battery.py --demo --preview-menu  # 只弹右键菜单，15 秒后退出
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
APP_NAME = "GPW Battery"
FONT_FACE = "Segoe UI"

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
WM_MOUSEMOVE = 0x0200
WM_APP = 0x8000
WM_CONTEXTMENU = 0x007B
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
NIN_SELECT = 0x0400

WM_TRAY = WM_APP + 1          # 托盘回调消息
WM_REFRESH_DONE = WM_APP + 2  # 后台线程读完后通知 UI

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
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

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0

DT_LEFT = 0x0000
DT_SINGLELINE = 0x0020
DT_NOPREFIX = 0x0800
DT_CALCRECT = 0x0400
DT_VCENTER = 0x0004
TRANSPARENT = 1
ANTIALIASED_QUALITY = 4
DEFAULT_CHARSET = 1
FW_NORMAL = 400
FW_SEMIBOLD = 600

SM_CXSMICON = 49
MONITOR_DEFAULTTONEAREST = 2

IDI_APPLICATION = 32512
ERROR_CLASS_ALREADY_EXISTS = 1410

CARD_GAP = 6      # 卡片与托盘图标的间距
CARD_EDGE = 4     # 卡片与屏幕/工作区边缘的最小距离

# 配色（仿 Win11 深色卡片）
CLR_BG = (43, 43, 43)
CLR_BORDER = (62, 62, 62)
CLR_HOVER = (58, 58, 58)
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


# ===================================================================== 绘制底座
class _MemDC:
    """借一个内存 DC 用来量文字（with 语法，退出时自动释放）"""

    def __enter__(self):
        self._screen = user32.GetDC(None)
        self._dc = gdi32.CreateCompatibleDC(self._screen)
        return self._dc

    def __exit__(self, *exc):
        gdi32.DeleteDC(self._dc)
        user32.ReleaseDC(None, self._screen)
        return False


class _Surface:
    """32 位 DIB 绘制面：画完交给 UpdateLayeredWindow，退出 with 时释放 GDI 资源"""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.hdc_screen = None
        self.mem = None
        self.bits = None
        self._hbm = None
        self._old_bmp = None

    def __enter__(self):
        self.hdc_screen = user32.GetDC(None)
        self.mem = gdi32.CreateCompatibleDC(self.hdc_screen)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self.w
        bmi.bmiHeader.biHeight = -self.h          # 负高度 = 自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        self.bits = ctypes.c_void_p()
        self._hbm = gdi32.CreateDIBSection(self.mem, ctypes.byref(bmi), DIB_RGB_COLORS,
                                           ctypes.byref(self.bits), None, 0)
        self._old_bmp = gdi32.SelectObject(self.mem, self._hbm)
        return self

    def __exit__(self, *exc):
        gdi32.SelectObject(self.mem, self._old_bmp)
        gdi32.DeleteObject(self._hbm)
        gdi32.DeleteDC(self.mem)
        user32.ReleaseDC(None, self.hdc_screen)
        return False

    def pixels(self):
        size = self.w * self.h * 4
        return ctypes.cast(self.bits, ctypes.POINTER(ctypes.c_ubyte * size)).contents


class LayeredCard:
    """
    Win11 风格圆角卡片的公共底座。

    左键弹窗和右键菜单都是「无边框置顶分层窗口 + GDI 绘制 + 逐像素圆角 alpha」，
    差别只在画什么。窗口创建、卡片底/描边、圆角合成、贴图标定位、显示隐藏这些
    共用部分收在这里，子类只要实现 `_measure_size()` / `_paint()` / `_wnd_proc()`。
    """

    RADIUS = 8          # 卡片圆角（96 DPI 下的像素）

    def __init__(self, app, class_name):
        self.app = app
        self.class_name = class_name
        self.hwnd = None
        self.visible = False
        self.rect = wintypes.RECT(0, 0, 0, 0)
        self._wndproc_ref = None
        self._dpi = 96

    # -- 窗口 ------------------------------------------------------
    def create(self):
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wnd_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(IDI_APPLICATION))
        wc.lpszClassName = self.class_name
        user32.RegisterClassExW(ctypes.byref(wc))
        ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        self.hwnd = user32.CreateWindowExW(ex, self.class_name, APP_NAME, WS_POPUP,
                                           0, 0, 10, 10, None, None, hinst, None)
        return self.hwnd

    # -- 尺寸与字体 -------------------------------------------------
    def _scaled(self, v):
        return int(round(v * self._dpi / 96.0))

    def _font(self, size, weight=FW_NORMAL):
        return gdi32.CreateFontW(-self._scaled(size), 0, 0, 0, weight, 0, 0, 0,
                                 DEFAULT_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0, FONT_FACE)

    @staticmethod
    def measure(dc, font, text):
        """单行文字的像素宽度"""
        old = gdi32.SelectObject(dc, font)
        rc = wintypes.RECT(0, 0, 0, 0)
        user32.DrawTextW(dc, text, -1, ctypes.byref(rc),
                         DT_LEFT | DT_SINGLELINE | DT_NOPREFIX | DT_CALCRECT)
        gdi32.SelectObject(dc, old)
        return rc.right - rc.left

    # -- 绘制基元 ---------------------------------------------------
    @staticmethod
    def _draw_card(dc, w, h, radius):
        """卡片底 + 1px 描边（深色背景上留一圈轮廓）"""
        bg = gdi32.CreateSolidBrush(RGB(*CLR_BG))
        user32.FillRect(dc, ctypes.byref(wintypes.RECT(0, 0, w, h)), bg)
        gdi32.DeleteObject(bg)

        pen = gdi32.CreatePen(0, 1, RGB(*CLR_BORDER))
        hollow = gdi32.CreateSolidBrush(RGB(*CLR_BG))
        old_pen = gdi32.SelectObject(dc, pen)
        old_brush = gdi32.SelectObject(dc, hollow)
        gdi32.RoundRect(dc, 0, 0, w, h, radius * 2, radius * 2)
        gdi32.SelectObject(dc, old_pen)
        gdi32.SelectObject(dc, old_brush)
        gdi32.DeleteObject(pen)
        gdi32.DeleteObject(hollow)

    @staticmethod
    def _fill_round(dc, x0, y0, x1, y1, radius, color):
        brush = gdi32.CreateSolidBrush(RGB(*color))
        old = gdi32.SelectObject(dc, brush)
        gdi32.RoundRect(dc, x0, y0, x1, y1, radius * 2, radius * 2)
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(brush)

    @staticmethod
    def _hline(dc, x0, x1, y, color=CLR_BORDER):
        pen = gdi32.CreatePen(0, 1, RGB(*color))
        old = gdi32.SelectObject(dc, pen)
        gdi32.MoveToEx(dc, x0, y, None)
        gdi32.LineTo(dc, x1, y)
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(pen)

    def _check_mark(self, dc, x, cy, color=CLR_TITLE):
        """两段折线勾：比字体里的 ✓ 更接近 Win11 的粗细和比例"""
        s = self._scaled
        pen = gdi32.CreatePen(0, max(1, s(1.5)), RGB(*color))
        old = gdi32.SelectObject(dc, pen)
        gdi32.MoveToEx(dc, x, cy, None)
        gdi32.LineTo(dc, x + s(4), cy + s(4))
        gdi32.LineTo(dc, x + s(11), cy - s(5))
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(pen)

    @staticmethod
    def _round_alpha(surf, radius):
        """把矩形 DIB 的四角抹成透明，边缘按覆盖率做 alpha 过渡"""
        w, h = surf.w, surf.h
        cov = _rounded_alpha(w, h, radius)
        buf = surf.pixels()
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

    def _present(self, surf):
        """推到屏幕：UpdateLayeredWindow 同时负责定位与 alpha 合成"""
        dst = wintypes.POINT(self.rect.left, self.rect.top)
        src = wintypes.POINT(0, 0)
        size = wintypes.SIZE(surf.w, surf.h)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.hwnd, surf.hdc_screen, ctypes.byref(dst),
                                   ctypes.byref(size), surf.mem, ctypes.byref(src), 0,
                                   ctypes.byref(blend), ULW_ALPHA)

    # -- 定位与显隐 -------------------------------------------------
    def _place(self, anchor, w, h, align="center"):
        """贴在 anchor 正上方；越界夹回工作区，任务栏在上方时改到下方"""
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        hmon = user32.MonitorFromRect(ctypes.byref(anchor), MONITOR_DEFAULTTONEAREST)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        work = mi.rcWork

        if align == "right":
            x = anchor.right - w
        elif align == "left":
            x = anchor.left
        else:
            x = (anchor.left + anchor.right) // 2 - w // 2

        gap, edge = self._scaled(CARD_GAP), CARD_EDGE
        y = min(anchor.top, work.bottom) - h - gap
        if y < work.top + edge:
            y = min(anchor.bottom + gap, work.bottom - h - edge)
        x = max(work.left + edge, min(x, work.right - w - edge))
        y = max(work.top + edge, min(y, work.bottom - h - edge))
        return wintypes.RECT(x, y, x + w, y + h)

    def _show(self, rect):
        self.rect = rect
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, rect.left, rect.top,
                            rect.right - rect.left, rect.bottom - rect.top,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW)
        self._paint()
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.visible = True

    def hide(self):
        if self.visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False

    def contains(self, pt):
        """点是否落在卡片矩形内（用于「点空白处收起」）"""
        if not self.visible:
            return False
        return (self.rect.left <= pt.x < self.rect.right and
                self.rect.top <= pt.y < self.rect.bottom)

    # -- 子类实现 ---------------------------------------------------
    def _measure_size(self):
        raise NotImplementedError

    def _paint(self):
        raise NotImplementedError

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        raise NotImplementedError


# ===================================================================== 左键弹窗
class Popup(LayeredCard):
    """仿 Win11 flyout 的电量卡片：设备名 + 电量状态 + 电量条"""

    def __init__(self, app):
        super().__init__(app, "GPWBatteryPopup")
        self._content = ("", "", None, False, True)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_PAINT:
            return 0                      # 内容全部由 UpdateLayeredWindow 画
        if msg == WM_LBUTTONUP:
            self.app.refresh()
            return 0
        if msg == WM_RBUTTONUP:
            self.hide()                   # 右键点卡片本身也收起
            return 0
        if msg == WM_DESTROY:
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -- 内容 ------------------------------------------------------
    @staticmethod
    def describe(reading):
        """把一次电量读数翻译成 (标题, 副标题, 电量, 充电中, 已连接)"""
        if reading is None:
            return ("GPW1", "正在读取…", None, False, True)

        title = reading.device_name or "GPW1"
        if not reading.error:
            level = reading.percent
            sub = (f"电量 {level}%  ·  {reading.status_text}"
                   if level is not None else "电量未知")
            return (title, sub, level, reading.charging, True)

        state = getattr(reading, "state", "")
        if state == "asleep":
            sub = "鼠标休眠 · 移动鼠标唤醒"
        elif state == "no_receiver":
            sub = "接收器无响应 · 请重新插拔"
        elif state == "absent" or "未连接" in reading.error:
            sub = "鼠标未连接 · 请打开电源"
        else:
            sub = "未检测到设备"
        return (title, sub, None, False, False)

    def _metrics(self):
        s = self._scaled
        return {
            "pad_x": s(16), "pad_y": s(13),
            "gap1": s(3), "gap2": s(9),
            "title_h": s(20), "sub_h": s(18),
            "bar_h": max(2, s(3)),
        }

    def _measure_size(self):
        m = self._metrics()
        f_title, f_sub = self._font(15, FW_SEMIBOLD), self._font(13)
        with _MemDC() as dc:
            tw = self.measure(dc, f_title, self._content[0])
            sw = self.measure(dc, f_sub, self._content[1])
        gdi32.DeleteObject(f_title)
        gdi32.DeleteObject(f_sub)
        w = max(tw, sw, self._scaled(132)) + m["pad_x"] * 2
        h = (m["pad_y"] * 2 + m["title_h"] + m["gap1"] + m["sub_h"]
             + m["gap2"] + m["bar_h"])
        return w, h

    def _paint(self):
        w = self.rect.right - self.rect.left
        h = self.rect.bottom - self.rect.top
        if w <= 0 or h <= 0:
            return
        m = self._metrics()
        radius = self._scaled(self.RADIUS)
        title, sub, level, charging, connected = self._content
        f_title, f_sub = self._font(15, FW_SEMIBOLD), self._font(13)

        with _Surface(w, h) as surf:
            dc = surf.mem
            self._draw_card(dc, w, h, radius)
            gdi32.SetBkMode(dc, TRANSPARENT)

            gdi32.SelectObject(dc, f_title)
            gdi32.SetTextColor(dc, RGB(*CLR_TITLE))
            user32.DrawTextW(dc, title, -1, ctypes.byref(wintypes.RECT(
                m["pad_x"], m["pad_y"],
                w - m["pad_x"], m["pad_y"] + m["title_h"])),
                DT_LEFT | DT_SINGLELINE | DT_NOPREFIX)

            gdi32.SelectObject(dc, f_sub)
            gdi32.SetTextColor(dc, RGB(*CLR_SUB))
            top = m["pad_y"] + m["title_h"] + m["gap1"]
            user32.DrawTextW(dc, sub, -1, ctypes.byref(wintypes.RECT(
                m["pad_x"], top, w - m["pad_x"], top + m["sub_h"])),
                DT_LEFT | DT_SINGLELINE | DT_NOPREFIX)

            self._draw_bar(dc, m["pad_x"], h - m["pad_y"] - m["bar_h"],
                           w - m["pad_x"], m["bar_h"], level, charging, connected)

            gdi32.GdiFlush()
            self._round_alpha(surf, radius)
            self._present(surf)

        gdi32.DeleteObject(f_title)
        gdi32.DeleteObject(f_sub)

    def _draw_bar(self, dc, x0, y0, x1, h, level, charging, connected):
        self._fill_round(dc, x0, y0, x1, y0 + h, h // 2, CLR_TRACK)
        if not (connected and level):
            return
        if charging:
            color = CLR_CHARGE
        elif level > 50:
            color = CLR_OK
        elif level > 20:
            color = CLR_MID
        else:
            color = CLR_LOW
        right = x0 + max(h, int(round((x1 - x0) * min(100, level) / 100.0)))
        self._fill_round(dc, x0, y0, right, y0 + h, h // 2, color)

    # -- 对外 ------------------------------------------------------
    def show_at(self, anchor, reading, dpi, align="center"):
        self._dpi = dpi
        self._content = self.describe(reading)
        self._show(self._place(anchor, *self._measure_size(), align=align))

    def refresh_content(self, reading, dpi):
        """数据变了就地重绘；尺寸变化时保持底边和水平中心不动"""
        if not self.visible:
            return
        self._dpi = dpi
        self._content = self.describe(reading)
        w, h = self._measure_size()
        if (w, h) == (self.rect.right - self.rect.left,
                      self.rect.bottom - self.rect.top):
            self._paint()
            return
        cx = (self.rect.left + self.rect.right) // 2
        bottom = self.rect.bottom
        self._show(wintypes.RECT(cx - w // 2, bottom - h, cx - w // 2 + w, bottom))


# ===================================================================== 右键菜单
class MenuPopup(LayeredCard):
    """
    与左键弹窗同风格的自绘右键菜单。

    系统的 TrackPopupMenu 画的是经典 Win32 菜单（浅色、直角、系统字体），
    和 Win11 卡片摆在一起很违和，所以这里用同一套底座自己画。
    """

    def __init__(self, app):
        super().__init__(app, "GPWBatteryMenu")
        self.items = []          # [(kind, label, cmd, checked)]，kind: "item" / "sep"
        self._hover = -1
        self._rows = []          # [(y0, y1, index)] 客户区坐标
        self._pad_x = 0
        self._width = 0

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_PAINT:
            return 0
        if msg == WM_MOUSEMOVE:
            self._set_hover(self._hit(*self._client_xy(lparam)))
            return 0
        if msg == WM_LBUTTONUP:
            item = self._item(self._hit(*self._client_xy(lparam)))
            self.hide()
            if item is not None:
                self.app._on_menu_command(item[2])
            return 0
        if msg == WM_RBUTTONUP:
            self.hide()
            return 0
        if msg == WM_DESTROY:
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -- 命中测试 ---------------------------------------------------
    @staticmethod
    def _client_xy(lparam):
        return (ctypes.c_short(lparam & 0xFFFF).value,
                ctypes.c_short((lparam >> 16) & 0xFFFF).value)

    def _item(self, idx):
        return self.items[idx] if 0 <= idx < len(self.items) else None

    def _hit(self, x, y):
        """
        客户区坐标 -> 条目序号。

        必须同时校验 x：卡片左右各有留白、圆角外还是透明区，只看 y 的话鼠标停在
        菜单侧面也会把某一项点亮。
        """
        if not (self._pad_x <= x <= self._width - self._pad_x):
            return -1
        for y0, y1, idx in self._rows:
            if y0 <= y < y1 and self.items[idx][0] == "item":
                return idx
        return -1

    def _set_hover(self, idx):
        if idx == self._hover:
            return
        self._hover = idx
        if self.visible:
            self._paint()

    def sync_hover(self, pt=None):
        """光标移出菜单后收不到 WM_MOUSEMOVE，由定时器兜底同步高亮"""
        if not self.visible:
            return
        if pt is None:
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
        if not self.contains(pt):
            self._set_hover(-1)
            return
        self._set_hover(self._hit(pt.x - self.rect.left, pt.y - self.rect.top))

    # -- 布局与绘制 -------------------------------------------------
    def _layout(self, w):
        s = self._scaled
        pad_y, item_h, sep_h = s(6), s(30), s(9)
        self._pad_x, self._width = s(6), w
        y = pad_y
        rows = []
        for i, it in enumerate(self.items):
            hh = sep_h if it[0] == "sep" else item_h
            rows.append((y, y + hh, i))
            y += hh
        self._rows = rows
        return y + pad_y

    def _measure_size(self):
        s = self._scaled
        pad_x, check_w = s(6), s(22)
        font = self._font(13)
        with _MemDC() as dc:
            widths = [self.measure(dc, font, it[1])
                      for it in self.items if it[0] == "item"]
        gdi32.DeleteObject(font)
        w = max(max(widths or [0]) + pad_x * 2 + check_w + s(18), s(150))
        return w, self._layout(w)

    def _paint(self):
        w = self.rect.right - self.rect.left
        h = self.rect.bottom - self.rect.top
        if w <= 0 or h <= 0:
            return
        s = self._scaled
        radius = s(self.RADIUS)
        pad_x, check_w = self._pad_x, s(22)
        font = self._font(13)

        with _Surface(w, h) as surf:
            dc = surf.mem
            self._draw_card(dc, w, h, radius)
            gdi32.SetBkMode(dc, TRANSPARENT)
            gdi32.SelectObject(dc, font)
            gdi32.SetTextColor(dc, RGB(*CLR_TITLE))

            for y0, y1, idx in self._rows:
                it = self.items[idx]
                if it[0] == "sep":
                    self._hline(dc, pad_x + s(6), w - pad_x - s(6), (y0 + y1) // 2)
                    continue
                if idx == self._hover:
                    self._fill_round(dc, pad_x, y0, w - pad_x, y1, s(4), CLR_HOVER)
                if it[3]:
                    self._check_mark(dc, pad_x + s(7), (y0 + y1) // 2)
                user32.DrawTextW(dc, it[1], -1, ctypes.byref(wintypes.RECT(
                    pad_x + check_w + s(4), y0, w - pad_x - s(10), y1)),
                    DT_LEFT | DT_SINGLELINE | DT_NOPREFIX | DT_VCENTER)

            gdi32.GdiFlush()
            self._round_alpha(surf, radius)
            self._present(surf)

        gdi32.DeleteObject(font)

    # -- 对外 ------------------------------------------------------
    def show_at(self, anchor, items, dpi, align="center"):
        self._dpi = dpi
        self.items = items
        self._hover = -1
        self._show(self._place(anchor, *self._measure_size(), align=align))


# ===================================================================== 主程序
class App:
    WINDOW_CLASS = "GPWBatteryTray"

    ID_TRAY = 1
    ID_TIMER_WATCH = 1
    ID_TIMER_REFRESH = 2
    WATCH_INTERVAL = 30       # 鼠标轮询间隔（毫秒）
    MENU_REFRESH = 1001
    MENU_AUTOSTART = 1002
    MENU_EXIT = 1003

    def __init__(self, demo=False):
        self.demo = demo
        self.hwnd = None
        self.hicon = None
        self.popup = None
        self.menu = None
        self.reading = None
        self.last_ok_time = 0.0
        self._lock = threading.Lock()
        self._monitor = None
        self._stop = threading.Event()
        self._wndproc_ref = None
        self._icon_rect = wintypes.RECT(0, 0, 0, 0)
        self._icon_rect_time = 0.0
        self._icon_fallback = False
        self._lbtn_down = False
        self._rbtn_down = False
        self._menu_shown_at = 0.0
        self._pending_refresh = False
        self._wm_taskbar_created = 0
        self._last_click_time = 0.0
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
        wc.lpszClassName = self.WINDOW_CLASS
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != ERROR_CLASS_ALREADY_EXISTS:
                raise OSError(f"RegisterClassEx 失败: {err}")
        self.hwnd = user32.CreateWindowExW(0, self.WINDOW_CLASS, APP_NAME,
                                           0, 0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            raise OSError("创建消息窗口失败")
        # Explorer 重启后会广播 TaskbarCreated，收到就重新挂上托盘图标
        self._wm_taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self.popup = Popup(self)
        self.popup.create()
        self.menu = MenuPopup(self)
        self.menu.create()
        self._add_tray_icon()
        user32.SetTimer(self.hwnd, self.ID_TIMER_WATCH, self.WATCH_INTERVAL, None)
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
    def _menu_items(self):
        return [
            ("item", "刷新电量", self.MENU_REFRESH, False),
            ("item", "开机自启动", self.MENU_AUTOSTART, self._autostart_enabled()),
            ("sep", "", 0, False),
            ("item", "退出", self.MENU_EXIT, False),
        ]

    def _anchor_rect(self):
        """托盘图标屏幕矩形；图标在隐藏区或坐标无效时退化为光标附近"""
        rc = self.icon_rect(max_age=0)
        if rc and not self._icon_fallback:
            return rc
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        size = max(16, user32.GetSystemMetrics(SM_CXSMICON))
        return wintypes.RECT(pt.x - size // 2, pt.y - size // 2,
                             pt.x + size // 2, pt.y + size // 2)

    def _show_menu(self):
        # 右键菜单弹出时，左键弹窗必须让位
        self.popup.hide()
        self._menu_shown_at = time.time()
        self.menu.show_at(self._anchor_rect(), self._menu_items(), self.dpi)

    def _on_menu_command(self, cmd):
        if cmd == self.MENU_REFRESH:
            self.refresh()
        elif cmd == self.MENU_AUTOSTART:
            self._toggle_autostart()
        elif cmd == self.MENU_EXIT:
            self.quit()

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

    def refresh(self):
        """立刻重新读一次（弹窗显示 / 手动刷新时用）"""
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

    # -- 点击 / 收起 ------------------------------------------------
    @staticmethod
    def _button_pressed(vk, was_down):
        """
        这一次轮询期间有没有按下该键。

        两路信号缺一不可：
        * `0x0001`（自上次调用以来按下过）—— 抓得住落在两次轮询之间的极快点击，
          但它会被「激活式点击」吃掉：点在非前台窗口上时系统先走激活流程，
          这个标志位有时不会置起来，只剩 `0x8000`。
        * 当前是否按住 + 与上次轮询比较的边沿 —— 激活式点击靠它兜底。
        """
        state = user32.GetAsyncKeyState(vk)
        down = bool(state & 0x8000)
        return bool(state & 0x0001) or (down and not was_down), down

    def _on_watch_timer(self):
        """
        轮询：左键/右键点在弹窗、菜单外面就收起。

        不用全局鼠标钩子（SetWindowsHookEx / WH_MOUSE_LL），避免被安全软件
        当成可疑行为。轮询间隔取 30ms，比常见的一次点击（80~150ms）短得多，
        两路信号都能稳定命中（见 `_button_pressed`）。
        """
        if not self.hwnd:
            return
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # 两个按键状态始终跟着刷新，避免弹窗出现时拿到过期的「上一次是否按住」
        l_pressed, self._lbtn_down = self._button_pressed(VK_LBUTTON, self._lbtn_down)
        r_pressed, self._rbtn_down = self._button_pressed(VK_RBUTTON, self._rbtn_down)
        if not (self.popup.visible or self.menu.visible):
            return
        if not (l_pressed or r_pressed):
            if self.menu.visible:
                self.menu.sync_hover(pt)
            return

        rc = self.icon_rect()
        over_icon = bool(rc) and not self._icon_fallback and \
            bool(user32.PtInRect(ctypes.byref(rc), pt))

        if l_pressed:
            if self.menu.visible and not self.menu.contains(pt):
                self.menu.hide()
            elif self.popup.visible and not self.popup.contains(pt) and not over_icon:
                self.popup.hide()

        # 右键：弹窗上一律收起；菜单上只认菜单外面的右键。
        # 菜单本身就是右键点出来的，那次按键要排除掉（over_icon + 刚弹出的时间窗）。
        if r_pressed and not over_icon:
            if self.menu.visible:
                if not self.menu.contains(pt) and \
                        time.time() - self._menu_shown_at > 0.25:
                    self.menu.hide()
            elif self.popup.visible:
                self.popup.hide()

        # 光标移出菜单后收不到 WM_MOUSEMOVE，这里补一次悬停高亮同步
        if self.menu.visible:
            self.menu.sync_hover(pt)

    def _show_popup(self):
        """左键弹出：锚点取托盘图标矩形，显示在图标正上方"""
        with self._lock:
            reading = self.reading
        self.menu.hide()
        self.popup.show_at(self._anchor_rect(), reading, self.dpi, align="center")
        # 数据超过 10 秒则顺手刷新一次
        if not self.demo and (time.time() - self.last_ok_time > 10 or reading is None):
            self.refresh()

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
                    # 右键：先收起左键弹窗，再弹出同风格自绘菜单
                    self._show_menu()
                    return 0
                if evt in (WM_LBUTTONUP, NIN_SELECT, WM_LBUTTONDBLCLK):
                    # 左键：切换弹窗（悬停不再触发）
                    #
                    # 注意：NOTIFYICON_VERSION_4 下，一次左键点击 Shell 会连发
                    # WM_LBUTTONUP 和 NIN_SELECT 两个事件，若都执行切换，弹窗
                    # 会「刚弹出就被自己关掉」。这里按时间做去抖，只认第一次。
                    now = time.time()
                    if now - self._last_click_time < 0.25:
                        return 0
                    self._last_click_time = now
                    if self.menu.visible:
                        self.menu.hide()
                    if self.popup.visible:
                        self.popup.hide()
                    else:
                        self._show_popup()
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
                if wparam == self.ID_TIMER_WATCH:
                    self._on_watch_timer()
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
            # 窗口过程里的异常如果只 print 到 stderr，打包成无控制台 exe 后就彻底消失了
            _log_exception(e)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def quit(self):
        self._stop.set()
        if self.hwnd:
            user32.KillTimer(self.hwnd, self.ID_TIMER_WATCH)
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
    if "--preview" in argv or "--preview-menu" in argv:
        # 直接显示弹窗/菜单并 15 秒后退出（用于截图检查样式）
        if "--preview-menu" in argv:
            app._show_menu()
        else:
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
