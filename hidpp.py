# -*- coding: utf-8 -*-
"""
hidpp.py —— 罗技 HID++ 协议（纯 ctypes，无第三方依赖）

支持：
  * HID++ 2.0  feature 0x1000 BATTERY_LEVEL_STATUS（首选）
  * HID++ 2.0  feature 0x1001 BATTERY_VOLTAGE     （回退，电压换算电量）
  * HID++ 1.0  register 0x07                      （老设备回退）
  * 接收器（Lightspeed / Unifying）与 USB 直连 / 蓝牙直连两种拓扑
"""

import ctypes
import time
from ctypes import wintypes

# ---------------------------------------------------------------- Win32 声明
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)

GUID_DEVINTERFACE_HID = "{4D1E55B2-F16F-11CF-88CB-001111000030}"
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
WAIT_OBJECT_0 = 0
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995

LOGITECH_VID = 0x046D
USAGE_PAGE_VENDOR = 0xFF00


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", ctypes.c_ulong), ("VendorID", ctypes.c_ushort),
                ("ProductID", ctypes.c_ushort), ("VersionNumber", ctypes.c_ushort)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", ctypes.c_ushort), ("UsagePage", ctypes.c_ushort),
                ("InputReportByteLength", ctypes.c_ushort),
                ("OutputReportByteLength", ctypes.c_ushort),
                ("FeatureReportByteLength", ctypes.c_ushort),
                ("Reserved", ctypes.c_ushort * 17),
                ("NumberLinkCollectionNodes", ctypes.c_ushort),
                ("NumberInputButtonCaps", ctypes.c_ushort),
                ("NumberInputValueCaps", ctypes.c_ushort),
                ("NumberInputDataIndices", ctypes.c_ushort),
                ("NumberOutputButtonCaps", ctypes.c_ushort),
                ("NumberOutputValueCaps", ctypes.c_ushort),
                ("NumberOutputDataIndices", ctypes.c_ushort),
                ("NumberFeatureButtonCaps", ctypes.c_ushort),
                ("NumberFeatureValueCaps", ctypes.c_ushort),
                ("NumberFeatureDataIndices", ctypes.c_ushort)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", ctypes.c_void_p)]


setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                          wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                 ctypes.POINTER(GUID), wintypes.DWORD,
                                                 ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

hid.HidD_GetAttributes.restype = wintypes.BOOL
hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOL
hid.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.restype = ctypes.c_long
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]

kernel32.CreateFileW.restype = ctypes.c_void_p
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CreateEventW.restype = ctypes.c_void_p
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.GetOverlappedResult.restype = wintypes.BOOL
kernel32.GetOverlappedResult.argtypes = [ctypes.c_void_p, ctypes.POINTER(OVERLAPPED),
                                         ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
kernel32.CancelIoEx.restype = wintypes.BOOL
kernel32.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.POINTER(OVERLAPPED)]
kernel32.ResetEvent.argtypes = [ctypes.c_void_p]


# ---------------------------------------------------------------- 设备枚举
def _guid_from_string(s):
    g = GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.create_unicode_buffer(s), ctypes.byref(g))
    return g


def enumerate_hid():
    """返回所有 HID 接口：dict(path, vid, pid, usage_page, usage, in_len, out_len)"""
    g = _guid_from_string(GUID_DEVINTERFACE_HID)
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not hdev or hdev == INVALID_HANDLE_VALUE:
        return []
    result = []
    did = SP_DEVICE_INTERFACE_DATA()
    did.cbSize = ctypes.sizeof(did)
    i = 0
    try:
        while setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(g), i,
                                                   ctypes.byref(did)):
            need = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(did), None, 0,
                                                      ctypes.byref(need), None)
            if not need.value:
                i += 1
                continue
            buf = ctypes.create_string_buffer(need.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W: DWORD cbSize + WCHAR DevicePath[]
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8
            ok = setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(did), buf, need.value, ctypes.byref(need), None)
            if ok:
                # 路径在结构体内偏移 4 字节处（而非对齐后的 8）
                path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
                info = _describe(path)
                if info:
                    result.append(info)
            i += 1
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return result


def _describe(path):
    h = kernel32.CreateFileW(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             None, OPEN_EXISTING, 0, None)
    if not h or h == INVALID_HANDLE_VALUE:
        return None
    try:
        at = HIDD_ATTRIBUTES()
        at.Size = ctypes.sizeof(at)
        if not hid.HidD_GetAttributes(h, ctypes.byref(at)):
            return None
        info = {"path": path, "vid": at.VendorID, "pid": at.ProductID,
                "usage_page": 0, "usage": 0, "in_len": 0, "out_len": 0}
        pp = ctypes.c_void_p()
        if hid.HidD_GetPreparsedData(h, ctypes.byref(pp)):
            caps = HIDP_CAPS()
            if hid.HidP_GetCaps(pp, ctypes.byref(caps)) == 0x110000:
                info["usage_page"] = caps.UsagePage
                info["usage"] = caps.Usage
                info["in_len"] = caps.InputReportByteLength
                info["out_len"] = caps.OutputReportByteLength
            hid.HidD_FreePreparsedData(pp)
        return info
    finally:
        kernel32.CloseHandle(h)


# ---------------------------------------------------------------- 设备句柄
class HidHandle:
    """带超时的 HID 读写封装（overlapped I/O）"""

    def __init__(self, path):
        self.path = path
        self.handle = kernel32.CreateFileW(
            path, GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED, None)
        if not self.handle or self.handle == INVALID_HANDLE_VALUE:
            raise OSError(f"无法打开设备 (err={ctypes.get_last_error()}): {path}")
        self._ev_write = kernel32.CreateEventW(None, True, False, None)
        self._ev_read = kernel32.CreateEventW(None, True, False, None)
        self._closed = False

    def write(self, data, timeout_ms=1000):
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        ov = OVERLAPPED()
        ov.hEvent = self._ev_write
        kernel32.ResetEvent(self._ev_write)
        written = wintypes.DWORD(0)
        ok = kernel32.WriteFile(self.handle, buf, len(data), ctypes.byref(written),
                                ctypes.byref(ov))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise OSError(f"WriteFile 失败 err={err}")
            if kernel32.WaitForSingleObject(self._ev_write, timeout_ms) != WAIT_OBJECT_0:
                kernel32.CancelIoEx(self.handle, ctypes.byref(ov))
                raise TimeoutError("HID 写入超时")
            if not kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov),
                                                ctypes.byref(written), False):
                raise OSError(f"GetOverlappedResult 失败 err={ctypes.get_last_error()}")
        return written.value

    def read(self, size, timeout_ms=1000, cancel_wait_ms=200):
        buf = ctypes.create_string_buffer(size)
        ov = OVERLAPPED()
        ov.hEvent = self._ev_read
        kernel32.ResetEvent(self._ev_read)
        got = wintypes.DWORD(0)
        ok = kernel32.ReadFile(self.handle, buf, size, ctypes.byref(got), ctypes.byref(ov))
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                if err in (ERROR_OPERATION_ABORTED, 6, 1167):  # 设备已移除
                    raise OSError(f"设备已断开 err={err}")
                raise OSError(f"ReadFile 失败 err={err}")
            if kernel32.WaitForSingleObject(self._ev_read, timeout_ms) != WAIT_OBJECT_0:
                kernel32.CancelIoEx(self.handle, ctypes.byref(ov))
                kernel32.WaitForSingleObject(self._ev_read, cancel_wait_ms)
                raise TimeoutError("HID 读取超时")
            if not kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov),
                                                ctypes.byref(got), False):
                raise OSError(f"GetOverlappedResult 失败 err={ctypes.get_last_error()}")
        return bytes(buf.raw[:got.value])

    def close(self):
        if not self._closed:
            self._closed = True
            if self.handle and self.handle != INVALID_HANDLE_VALUE:
                kernel32.CloseHandle(self.handle)
            for ev in (self._ev_read, self._ev_write):
                if ev:
                    kernel32.CloseHandle(ev)
            self.handle = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------- HID++ 协议
HIDPP_SHORT = 0x10
HIDPP_LONG = 0x11
SW_ID = 0x01

FEATURE_ROOT = 0x0000
FEATURE_DEVICE_NAME = 0x0005
FEATURE_BATTERY_LEVEL_STATUS = 0x1000
FEATURE_BATTERY_VOLTAGE = 0x1001
FEATURE_UNIFIED_BATTERY = 0x1004

# 电量状态
STATUS_DISCHARGING = 0
STATUS_CHARGING = 1
STATUS_CHARGE_COMPLETE = 2
STATUS_CHARGING_SLOW = 3
STATUS_INVALID = 4


class HidppError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


class HidppDevice:
    """
    一个 HID++ 通道。
    receiver=True 时表示这是接收器，device_index 指向配对的鼠标（1..6）；
    否则为设备直连，device_index 固定 0xFF。
    """

    def __init__(self, info, receiver=True, device_index=0x01):
        self.info = info
        self.receiver = receiver
        self.device_index = device_index
        self.handle = HidHandle(info["path"])
        self.long_report = info["usage"] == 0x02 or info["out_len"] >= 20
        self._feature_cache = {}
        self.name = None

    # -- 底层收发 ---------------------------------------------------
    def _send(self, feat_idx, func, params=b"", timeout_ms=1200, retries=1):
        swid_func = ((func & 0x0F) << 4) | SW_ID
        if self.long_report:
            length = max(20, self.info["out_len"] or 20)
            pkt = bytearray([HIDPP_LONG, self.device_index, feat_idx, swid_func])
            pkt += bytes(params[: length - 4]).ljust(length - 4, b"\x00")
        else:
            length = max(7, self.info["out_len"] or 7)
            pkt = bytearray([HIDPP_SHORT, self.device_index, feat_idx, swid_func])
            pkt += bytes(params[: length - 4]).ljust(length - 4, b"\x00")

        last = None
        for attempt in range(retries + 1):
            try:
                return self._send_once(bytes(pkt[:length]), feat_idx, length, timeout_ms)
            except HidppError as e:
                # 只有超时才重试（鼠标休眠唤醒后第一次请求常常丢失）
                if e.code is not None:
                    raise
                last = e
                time.sleep(0.05)
        raise last

    def _send_once(self, pkt, feat_idx, length, timeout_ms):
        # 清掉可能残留的通知报文
        self._drain()
        self.handle.write(pkt, timeout_ms)
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            remain = max(20, int((deadline - time.time()) * 1000))
            try:
                resp = self.handle.read(self.info["in_len"] or length, remain)
            except TimeoutError:
                raise HidppError("设备无响应（超时）")
            if len(resp) < 4:
                continue
            rid = resp[0]
            if rid not in (HIDPP_SHORT, HIDPP_LONG):
                continue
            if resp[1] != self.device_index:
                continue
            # 错误响应：[rid, devIdx, 0x8F, featureIdx, funcSwid, errorCode, ...]
            if resp[2] == 0x8F:
                code = resp[5] if len(resp) > 5 else None
                raise HidppError(f"设备返回错误 0x{code:02X}" if code is not None
                                 else "设备返回错误", code=code)
            if resp[2] != feat_idx:
                continue
            if (resp[3] & 0x0F) != SW_ID:
                continue
            return resp
        raise HidppError("等待响应超时")

    def _drain(self, max_ms=30):
        deadline = time.time() + max_ms / 1000.0
        while time.time() < deadline:
            try:
                self.handle.read(self.info["in_len"] or 20, 1, cancel_wait_ms=25)
            except Exception:
                break

    # -- 上层 API ---------------------------------------------------
    def ping(self):
        """用 root.getProtocolVersion 判断该 index 上是否有 HID++2.0 设备"""
        try:
            resp = self._send(FEATURE_ROOT, 0x1, b"", timeout_ms=700)
            return len(resp) >= 5
        except Exception:
            return False

    def get_feature(self, feature_id):
        if feature_id in self._feature_cache:
            return self._feature_cache[feature_id]
        resp = self._send(FEATURE_ROOT, 0x0,
                          bytes([(feature_id >> 8) & 0xFF, feature_id & 0xFF]))
        idx = resp[4] if len(resp) > 4 else 0
        if idx == 0:
            raise HidppError(f"设备不支持 feature 0x{feature_id:04X}")
        self._feature_cache[feature_id] = idx
        return idx

    def has_feature(self, feature_id):
        try:
            self.get_feature(feature_id)
            return True
        except Exception:
            return False

    def read_name(self):
        """feature 0x0005 DEVICE_NAME"""
        try:
            idx = self.get_feature(FEATURE_DEVICE_NAME)
        except Exception:
            return None
        try:
            resp = self._send(idx, 0x0, bytes([0x00]))
            length = resp[4]
            if length == 0 or length > 40:
                return None
            text = resp[5:5 + length]
            name = text.decode("utf-8", "ignore").strip("\x00").strip()
            return name or None
        except Exception:
            return None

    # 设备不存在/不支持时，不必再试其它 feature
    ABSENT_CODES = (0x08, 0x09)

    def read_battery(self):
        """返回 (percent, status, voltage_mv, source)"""
        errors = []

        # 1) 0x1000 BATTERY_LEVEL_STATUS
        try:
            idx = self.get_feature(FEATURE_BATTERY_LEVEL_STATUS)
            resp = self._send(idx, 0x0, b"")
            level = resp[4]
            status = resp[5] if len(resp) > 5 else STATUS_INVALID
            volt = (resp[6] << 8 | resp[7]) if len(resp) > 7 else 0
            if 0 < level <= 100:
                return level, status, volt, "0x1000"
            errors.append(f"0x1000 电量无效({level})")
        except HidppError as e:
            if e.code in self.ABSENT_CODES:
                raise
            errors.append(f"0x1000: {e}")
        except Exception as e:
            errors.append(f"0x1000: {e}")

        # 2) 0x1001 BATTERY_VOLTAGE
        try:
            idx = self.get_feature(FEATURE_BATTERY_VOLTAGE)
            resp = self._send(idx, 0x0, b"")
            volt = (resp[4] << 8) | resp[5]
            if 3000 <= volt <= 4500:
                return voltage_to_percent(volt), STATUS_INVALID, volt, "0x1001"
            errors.append(f"0x1001 电压异常({volt})")
        except HidppError as e:
            if e.code in self.ABSENT_CODES:
                raise
            errors.append(f"0x1001: {e}")
        except Exception as e:
            errors.append(f"0x1001: {e}")

        # 3) HID++ 1.0 register 0x07
        try:
            level = self._read_battery_hidpp10()
            if level is not None:
                return level, STATUS_INVALID, 0, "1.0/0x07"
        except Exception as e:
            errors.append(f"1.0/0x07: {e}")

        raise HidppError("; ".join(errors) or "读取电量失败")

    def _read_battery_hidpp10(self):
        """老协议：register 0x07。返回百分比或 None。"""
        if self.long_report:
            raise HidppError("仅短报文接口支持 1.0")
        # request: [0x10, idx, 0x83, 0x07, 0x10, 0x00, 0x00]
        self._drain()
        pkt = bytes([HIDPP_SHORT, self.device_index, 0x83, 0x07, 0x10, 0x00, 0x00])
        self.handle.write(pkt, 800)
        deadline = time.time() + 0.8
        while time.time() < deadline:
            try:
                resp = self.handle.read(self.info["in_len"] or 7,
                                        max(20, int((deadline - time.time()) * 1000)))
            except TimeoutError:
                return None
            if len(resp) < 7 or resp[0] != HIDPP_SHORT:
                continue
            if resp[1] != self.device_index or resp[2] != 0x07:
                continue
            data = resp[3:7]
            flags = data[0]
            # 统一电量（unified battery）
            if flags & 0x03:
                level = data[1]
                if 0 <= level <= 100:
                    return level
            # 电压法
            volt = (data[1] << 8) | data[2]
            if 3000 <= volt <= 4500:
                return voltage_to_percent(volt)
        return None


def voltage_to_percent(mv):
    """锂电电压 → 百分比（罗技常用近似曲线）"""
    table = [(4186, 100), (4067, 90), (3989, 80), (3922, 70), (3859, 60),
             (3811, 50), (3778, 40), (3751, 30), (3717, 20), (3671, 10),
             (3646, 5), (3579, 2), (3500, 0)]
    if mv >= table[0][0]:
        return 100
    for (v1, p1), (v2, p2) in zip(table, table[1:]):
        if mv >= v2:
            ratio = (mv - v2) / float(v1 - v2)
            return max(0, min(100, int(round(p2 + ratio * (p1 - p2)))))
    return 0


# ---------------------------------------------------------------- 顶层探测
class BatteryReading:
    """
    state 取值：
      ok          读取成功
      asleep      接收器正常、设备已配对，但鼠标在休眠（省电）不响应
      absent      接收器正常，但没有已配对的设备
      no_receiver 找不到/联系不上接收器
    """

    def __init__(self, percent=None, status=STATUS_INVALID, voltage=0,
                 device_name="", transport="", error=None, source="", state="ok"):
        self.percent = percent
        self.status = status
        self.voltage = voltage
        self.device_name = device_name
        self.transport = transport
        self.error = error
        self.source = source
        self.state = state
        self.timestamp = time.time()

    @property
    def charging(self):
        return self.status in (STATUS_CHARGING, STATUS_CHARGING_SLOW)

    @property
    def full(self):
        return self.status == STATUS_CHARGE_COMPLETE

    @property
    def status_text(self):
        if self.error:
            return "未连接"
        if self.status == STATUS_CHARGING:
            return "充电中"
        if self.status == STATUS_CHARGING_SLOW:
            return "缓慢充电"
        if self.status == STATUS_CHARGE_COMPLETE:
            return "已充满"
        if self.percent is not None:
            return "使用中"
        return "未知"

    def __repr__(self):
        return (f"BatteryReading(percent={self.percent}, status={self.status}, "
                f"voltage={self.voltage}, name={self.device_name!r}, "
                f"transport={self.transport!r}, error={self.error!r})")


# 已知 GPW1 相关 PID（仅用于友好命名/日志，不作为唯一判定条件）
KNOWN_PIDS = {
    0xC539: "Lightspeed 接收器",
    0xC088: "G PRO Wireless (USB)",
    0xC08F: "G PRO Wireless (USB)",
    0xC547: "Lightspeed 接收器",
    0xC52B: "Unifying 接收器",
    0xC532: "Unifying 接收器",
}

# 罗技接收器 PID（设备编号为 1..6）
RECEIVER_PIDS = {0xC539, 0xC547, 0xC52B, 0xC532, 0xC548, 0xC53F, 0xC534, 0xC52F}


def _hidpp_channels():
    """找出所有可作为 HID++ 通道的接口，接收器优先"""
    channels = []
    for info in enumerate_hid():
        if info["vid"] != LOGITECH_VID:
            continue
        if info["usage_page"] != USAGE_PAGE_VENDOR:
            continue
        if info["usage"] not in (0x01, 0x02):
            continue
        info["receiver"] = info["pid"] in RECEIVER_PIDS
        channels.append(info)
    # 长报文接口优先（能读更多 feature），接收器优先
    channels.sort(key=lambda i: (not i["receiver"], i["usage"] != 0x02))
    return channels


def _candidate_devices(channel):
    if channel["receiver"]:
        return [0x01, 0x02, 0x03, 0x04, 0x05, 0x06]
    return [0xFF]


def _channel_responds(info, timeout_ms=900):
    """该 HID++ 通道是否有任何响应（哪怕设备返回错误码，也说明通道是活的）"""
    dev = None
    try:
        dev = HidppDevice(info, receiver=info["receiver"],
                          device_index=0x01 if info["receiver"] else 0xFF)
        try:
            dev._send(FEATURE_ROOT, 0x0, bytes([0x10, 0x00]), timeout_ms=timeout_ms)
            return True
        except HidppError as e:
            return e.code is not None       # 有错误码 = 设备/接收器在线
        except Exception:
            return False
    finally:
        if dev is not None:
            dev.handle.close()


def read_battery(preferred_name=None, verbose=False, budget=6.0):
    """
    探测所有 HID++ 通道，返回第一个成功读到的 BatteryReading。
    失败时返回带 error 的 BatteryReading。
    budget: 整体探测时间上限（秒），避免鼠标离线时长时间阻塞。
    """
    deadline = time.time() + budget
    channels = _hidpp_channels()
    if not channels:
        return BatteryReading(error="未找到罗技接收器（请确认接收器已插好）")

    receiver_answered = False
    device_asleep = False
    errors = []
    any_channel_alive = False
    for info in channels:
        if time.time() > deadline:
            break
        if not _channel_responds(info):
            if verbose:
                print(f"[--] {info['pid']:04X} usage={info['usage']} 通道无响应，跳过")
            continue
        any_channel_alive = True
        for dev_idx in _candidate_devices(info):
            if time.time() > deadline:
                break
            dev = None
            try:
                dev = HidppDevice(info, receiver=info["receiver"], device_index=dev_idx)
                percent, status, volt, source = dev.read_battery()
                name = dev.read_name()
                if not name:
                    # 接收器通道上通常读不到型号名（需要长报文），用默认名
                    name = "GPW1" if info["receiver"] else KNOWN_PIDS.get(info["pid"], "GPW1")
                transport = "接收器" if info["receiver"] else "直连"
                reading = BatteryReading(
                    percent=percent, status=status, voltage=volt,
                    device_name=name, transport=transport, source=source)
                if verbose:
                    print(f"[OK] {name} idx={dev_idx:#04x} {transport} "
                          f"battery={percent}% status={status} volt={volt}mV via {source}")
                return reading
            except Exception as e:
                code = getattr(e, "code", None)
                # 0x08 未知设备（该编号没配对设备）/ 0x09 设备不响应（已配对但在休眠）
                if code == 0x09:
                    receiver_answered = True
                    device_asleep = True
                elif code == 0x08:
                    receiver_answered = True
                elif code is not None:
                    receiver_answered = True
                    errors.append(f"{info['pid']:04X}/{dev_idx:#04x}: {e}")
                else:
                    errors.append(f"{info['pid']:04X}/{dev_idx:#04x}: {e}")
                if verbose:
                    print(f"[..] {info['pid']:04X} idx={dev_idx:#04x} -> "
                          f"{type(e).__name__}: {e} (code={code})")
            finally:
                if dev is not None:
                    dev.handle.close()

    if device_asleep:
        return BatteryReading(error="鼠标休眠中（移动一下鼠标唤醒）", state="asleep")
    if receiver_answered:
        msg = "未检测到鼠标（请确认已配对/已开机）"
        state = "absent"
    elif not any_channel_alive:
        msg = "接收器无响应（请重新插拔接收器）"
        state = "no_receiver"
    else:
        msg = "未检测到罗技鼠标"
        state = "absent"
    if errors:
        msg += f"｜{errors[-1]}"
    return BatteryReading(error=msg, state=state)


if __name__ == "__main__":
    import sys
    r = read_battery(verbose="-v" in sys.argv)
    print(r)
    if r.percent is not None:
        print(f"电量：{r.percent}%  状态：{r.status_text}  "
              f"电压：{r.voltage}mV  设备：{r.device_name}  链路：{r.transport}")
    else:
        print("读取失败：", r.error)
