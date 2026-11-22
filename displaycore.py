"""Low-level Windows display control: DisplayConfig (HDR / SDR white level) + GDI gamma ramps."""
import ctypes
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

QDC_ONLY_ACTIVE_PATHS = 0x2
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9
DISPLAYCONFIG_DEVICE_INFO_GET_SDR_WHITE_LEVEL = 11
DISPLAYCONFIG_DEVICE_INFO_SET_SDR_WHITE_LEVEL = -18  # 0xFFFFFFEE, undocumented (used by the Settings app)


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", W.DWORD), ("HighPart", W.LONG)]


class PATH_SOURCE(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("statusFlags", ctypes.c_uint32)]


class PATH_TARGET(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_uint32), ("rotation", ctypes.c_uint32), ("scaling", ctypes.c_uint32),
                ("refreshNum", ctypes.c_uint32), ("refreshDen", ctypes.c_uint32),
                ("scanLineOrdering", ctypes.c_uint32), ("targetAvailable", W.BOOL), ("statusFlags", ctypes.c_uint32)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE), ("targetInfo", PATH_TARGET), ("flags", ctypes.c_uint32)]


class MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapterId", LUID),
                ("data", ctypes.c_byte * 48)]


class HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int32), ("size", ctypes.c_uint32), ("adapterId", LUID), ("id", ctypes.c_uint32)]


class SOURCE_NAME(ctypes.Structure):
    _fields_ = [("header", HEADER), ("viewGdiDeviceName", ctypes.c_wchar * 32)]


class TARGET_NAME(ctypes.Structure):
    _fields_ = [("header", HEADER), ("flags", ctypes.c_uint32), ("outputTechnology", ctypes.c_uint32),
                ("edidManufactureId", ctypes.c_uint16), ("edidProductCodeId", ctypes.c_uint16),
                ("connectorInstance", ctypes.c_uint32), ("monitorFriendlyDeviceName", ctypes.c_wchar * 64),
                ("monitorDevicePath", ctypes.c_wchar * 128)]


class ADV_COLOR_INFO(ctypes.Structure):
    _fields_ = [("header", HEADER), ("value", ctypes.c_uint32), ("colorEncoding", ctypes.c_int32),
                ("bitsPerColorChannel", ctypes.c_uint32)]


class SDR_WHITE_LEVEL(ctypes.Structure):
    _fields_ = [("header", HEADER), ("SDRWhiteLevel", ctypes.c_uint32)]


class SET_SDR_WHITE_LEVEL(ctypes.Structure):
    _fields_ = [("header", HEADER), ("SDRWhiteLevel", ctypes.c_uint32), ("finalValue", ctypes.c_ubyte)]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("DeviceName", ctypes.c_wchar * 32), ("DeviceString", ctypes.c_wchar * 128),
                ("StateFlags", W.DWORD), ("DeviceID", ctypes.c_wchar * 128), ("DeviceKey", ctypes.c_wchar * 128)]


DISPLAY_DEVICE_PRIMARY_DEVICE = 0x4

user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
user32.DisplayConfigSetDeviceInfo.argtypes = [ctypes.c_void_p]
gdi32.CreateDCW.restype = W.HDC
gdi32.CreateDCW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [W.HDC]
gdi32.GetDeviceGammaRamp.argtypes = [W.HDC, ctypes.c_void_p]
gdi32.SetDeviceGammaRamp.argtypes = [W.HDC, ctypes.c_void_p]

Ramp = (ctypes.c_uint16 * 256) * 3


def _hdr(struct, typ, adapter, id_):
    s = struct()
    s.header.type = typ
    s.header.size = ctypes.sizeof(struct)
    s.header.adapterId = adapter
    s.header.id = id_
    return s


def _get(struct, typ, adapter, id_):
    s = _hdr(struct, typ, adapter, id_)
    rc = user32.DisplayConfigGetDeviceInfo(ctypes.byref(s))
    if rc != 0:
        raise OSError(f"DisplayConfigGetDeviceInfo(type={typ}) failed: {rc}")
    return s


def primary_gdi_name():
    i = 0
    while True:
        dd = DISPLAY_DEVICEW(cb=ctypes.sizeof(DISPLAY_DEVICEW))
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            return None
        if dd.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE:
            return dd.DeviceName
        i += 1


class Display:
    def __init__(self, path):
        self.src_adapter = path.sourceInfo.adapterId
        self.src_id = path.sourceInfo.id
        self.tgt_adapter = path.targetInfo.adapterId
        self.tgt_id = path.targetInfo.id
        self.gdi_name = _get(SOURCE_NAME, DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
                             self.src_adapter, self.src_id).viewGdiDeviceName
        self.friendly = _get(TARGET_NAME, DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME,
                             self.tgt_adapter, self.tgt_id).monitorFriendlyDeviceName

    # ---- HDR / SDR white level ----
    def advanced_color(self):
        v = _get(ADV_COLOR_INFO, DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO, self.tgt_adapter, self.tgt_id)
        return {"supported": bool(v.value & 1), "enabled": bool(v.value & 2), "bpc": v.bitsPerColorChannel}

    def sdr_white_nits(self):
        v = _get(SDR_WHITE_LEVEL, DISPLAYCONFIG_DEVICE_INFO_GET_SDR_WHITE_LEVEL, self.tgt_adapter, self.tgt_id)
        return v.SDRWhiteLevel * 80 / 1000  # stored as 1000 * (nits / 80)

    def set_sdr_white_nits(self, nits, final=True):
        nits = max(80.0, min(480.0, float(nits)))
        s = _hdr(SET_SDR_WHITE_LEVEL, DISPLAYCONFIG_DEVICE_INFO_SET_SDR_WHITE_LEVEL, self.tgt_adapter, self.tgt_id)
        s.SDRWhiteLevel = int(round(nits * 1000 / 80))
        s.finalValue = 1 if final else 0
        rc = user32.DisplayConfigSetDeviceInfo(ctypes.byref(s))
        if rc != 0:
            raise OSError(f"Set SDR white level failed: {rc}")

    # ---- gamma ramp ----
    def get_ramp(self):
        hdc = gdi32.CreateDCW(None, self.gdi_name, None, None)
        try:
            r = Ramp()
            if not gdi32.GetDeviceGammaRamp(hdc, ctypes.byref(r)):
                raise OSError("GetDeviceGammaRamp failed")
            return r
        finally:
            gdi32.DeleteDC(hdc)

    def set_ramp(self, r):
        hdc = gdi32.CreateDCW(None, self.gdi_name, None, None)
        try:
            if not gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(r)):
                raise OSError(f"SetDeviceGammaRamp failed (err {ctypes.get_last_error()})")
        finally:
            gdi32.DeleteDC(hdc)


def active_displays():
    np_, nm = ctypes.c_uint32(), ctypes.c_uint32()
    user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(np_), ctypes.byref(nm))
    paths = (PATH_INFO * np_.value)()
    modes = (MODE_INFO * nm.value)()
    rc = user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(np_), paths, ctypes.byref(nm), modes, None)
    if rc != 0:
        raise OSError(f"QueryDisplayConfig failed: {rc}")
    return [Display(paths[i]) for i in range(np_.value)]


def primary_display():
    name = primary_gdi_name()
    for d in active_displays():
        if d.gdi_name == name:
            return d
    raise RuntimeError("Primary display not found")


# ---- NVIDIA-control-panel-style ramp math ----
def build_ramp(brightness=0.0, contrast=0.0, gamma=1.0):
    """brightness/contrast in -1..+1 (0 = neutral), gamma 0.3..2.8 (1.0 = neutral).
    Same model as NVCP 'Adjust desktop colour settings', which writes the GPU's LUT."""
    r = Ramp()
    for i in range(256):
        x = i / 255.0
        y = x ** (1.0 / gamma)                   # gamma
        y = (y - 0.5) * (1.0 + contrast) + 0.5   # contrast around mid-grey
        y = y + brightness * 0.5                 # brightness offset
        v = int(round(max(0.0, min(1.0, y)) * 65535))
        for c in range(3):
            r[c][i] = v
    return r
