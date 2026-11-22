"""Windows Night Light CloudStore bridge (Windows 11, undocumented format).

Reads and edits only the current user's two Night Light REG_BINARY values.
Preserves every unmodified Bond field; never invents missing registry keys.
See https://github.com/kvnxiao/win-nightlight-cli/blob/main/docs/nightlight-registry-format.md
"""
import time
from dataclasses import dataclass

try:
    import winreg
except ImportError:  # Allows portable codec tests on non-Windows CI hosts.
    winreg = None


class NightLightError(OSError):
    pass


PREFIX = b"CB\x01\x00"
ROOT = (r"Software\Microsoft\Windows\CurrentVersion\CloudStore\Store"
        r"\DefaultAccount\Current\default$windows.data.bluelightreduction.")
SETTINGS = "settings"
STATE = "bluelightreductionstate"
STOP, BOOL, UINT64, STRUCT, LIST, INT8, INT16, INT32 = 0, 2, 6, 10, 11, 14, 15, 16
MIN_K, MAX_K = 1200, 6500


def _uvar(data, pos):
    value = 0
    for i in range(10):
        if pos >= len(data):
            raise NightLightError("Truncated Night Light Bond varint")
        b = data[pos]
        pos += 1
        value |= (b & 127) << (7 * i)
        if not b & 128:
            if value > (1 << 64) - 1:
                raise NightLightError("Night Light varint overflow")
            return value, pos
    raise NightLightError("Invalid Night Light varint")


def _packvar(value):
    if not (0 <= value <= (1 << 64) - 1):
        raise ValueError("varint out of range")
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _zigzag(value):
    return _packvar((value << 1) ^ (value >> 63))


@dataclass(frozen=True)
class Field:
    id: int
    typ: int
    start: int
    value: int
    end: int


def _skip(data, pos, typ):
    if typ in (BOOL, 3, INT8):
        end = pos + 1
    elif typ in (4, 5, UINT64, INT16, INT32, 17):
        _, end = _uvar(data, pos)
    elif typ == 7:
        end = pos + 4
    elif typ == 8:
        end = pos + 8
    elif typ in (9, 18):
        count, start = _uvar(data, pos)
        end = start + count * (2 if typ == 18 else 1)
    elif typ == STRUCT:
        _, end = _scan(data, pos)
    elif typ in (LIST, 12):
        if pos >= len(data):
            raise NightLightError("Missing Night Light element type")
        element = data[pos] & 31
        count, end = _uvar(data, pos + 1)
        if count > len(data):
            raise NightLightError("Invalid Night Light list length")
        if element in (INT8, BOOL, 3):
            end += count
        else:
            for _ in range(count):
                end = _skip(data, end, element)
    elif typ == 13:
        if pos + 2 > len(data):
            raise NightLightError("Missing Night Light map types")
        key, value = data[pos] & 31, data[pos + 1] & 31
        count, end = _uvar(data, pos + 2)
        if count > len(data):
            raise NightLightError("Invalid Night Light map length")
        for _ in range(count):
            end = _skip(data, end, key)
            end = _skip(data, end, value)
    else:
        raise NightLightError(f"Unsupported Night Light Bond type {typ}")
    if end > len(data):
        raise NightLightError("Truncated Night Light Bond field")
    return end


def _scan(data, pos=0):
    fields = []
    while pos < len(data):
        start = pos
        header = data[pos]
        pos += 1
        typ, id_code = header & 31, header >> 5
        if typ == STOP:
            if header != 0:
                raise NightLightError("Unexpected Night Light Bond terminator")
            return fields, pos
        if id_code == 6:
            if pos >= len(data):
                raise NightLightError("Truncated Night Light field ID")
            field_id = data[pos]
            pos += 1
        elif id_code == 7:
            if pos + 2 > len(data):
                raise NightLightError("Truncated Night Light field ID")
            field_id = int.from_bytes(data[pos:pos + 2], "little")
            pos += 2
        else:
            field_id = id_code
        end = _skip(data, pos, typ)
        fields.append(Field(field_id, typ, start, pos, end))
        pos = end
    raise NightLightError("Missing Night Light Bond terminator")


def _one(data, fields, field_id, expected_type, optional=False):
    selected = [f for f in fields if f.id == field_id]
    if not selected and optional:
        return None
    if len(selected) != 1 or selected[0].typ != expected_type:
        raise NightLightError(f"Unexpected Night Light field {field_id}")
    return selected[0]


def _make(field_id, typ, content):
    if field_id < 6:
        prefix = bytes([(field_id << 5) | typ])
    elif field_id <= 255:
        prefix = bytes([192 | typ, field_id])
    else:
        prefix = bytes([224 | typ]) + field_id.to_bytes(2, "little")
    return prefix + content


def _patch_struct(original, field_id, replacement):
    fields, end = _scan(original)
    if end != len(original):
        raise NightLightError("Unexpected Night Light trailing bytes")
    out, done = bytearray(), False
    for f in fields:
        if not done and f.id > field_id and replacement is not None:
            out.extend(replacement)
            done = True
        if f.id == field_id:
            if done:
                raise NightLightError("Duplicate Night Light field")
            done = True
            if replacement is not None:
                out.extend(replacement)
        else:
            out.extend(original[f.start:f.end])
    if not done and replacement is not None:
        out.extend(replacement)
    out.append(STOP)
    return bytes(out)


@dataclass(frozen=True)
class Record:
    raw: bytes
    outer: bytes
    container: bytes
    wrapper: bytes
    inner: bytes
    stamp: int


def _unpack_record(raw):
    if not isinstance(raw, bytes) or not raw.startswith(PREFIX):
        raise NightLightError("Unsupported Night Light CloudStore envelope")
    outer = raw[len(PREFIX):]
    fields, end = _scan(outer)
    if end != len(outer):
        raise NightLightError("Unexpected Night Light envelope suffix")
    container_f = _one(outer, fields, 1, STRUCT)
    container = outer[container_f.value:container_f.end]
    cf, _ = _scan(container)
    stamp_f = _one(container, cf, 0, UINT64)
    stamp, _ = _uvar(container, stamp_f.value)
    wrapper_f = _one(container, cf, 1, STRUCT)
    wrapper = container[wrapper_f.value:wrapper_f.end]
    wf, _ = _scan(wrapper)
    payload_f = _one(wrapper, wf, 1, LIST)
    value = wrapper[payload_f.value:payload_f.end]
    if not value or value[0] != INT8:
        raise NightLightError("Unexpected Night Light payload list type")
    count, at = _uvar(value, 1)
    inner = value[at:]
    if count != len(inner) or not inner.startswith(PREFIX):
        raise NightLightError("Unexpected Night Light payload length")
    _, end = _scan(inner, len(PREFIX))
    if end != len(inner):
        raise NightLightError("Unexpected Night Light payload suffix")
    return Record(raw, outer, container, wrapper, inner, stamp)


def _repack_record(record, inner, timestamp):
    new_list = _make(1, LIST, bytes([INT8]) + _packvar(len(inner)) + inner)
    wrapper = _patch_struct(record.wrapper, 1, new_list)
    container = _patch_struct(record.container, 1, _make(1, STRUCT, wrapper))
    container = _patch_struct(container, 0, _make(0, UINT64, _packvar(timestamp)))
    outer = _patch_struct(record.outer, 1, _make(1, STRUCT, container))
    result = PREFIX + outer
    _unpack_record(result)  # Never write malformed or truncated data.
    return result


def _read_temp(inner):
    fields, _ = _scan(inner, len(PREFIX))
    f = _one(inner, fields, 40, INT16, optional=True)
    if f is None:
        return MAX_K
    u, _ = _uvar(inner, f.value)
    k = (u >> 1) ^ -(u & 1)
    if not MIN_K <= k <= MAX_K:
        raise NightLightError(f"Unsupported Night Light temperature: {k}K")
    return k


def _read_on(inner):
    fields, _ = _scan(inner, len(PREFIX))
    f = _one(inner, fields, 0, INT32, optional=True)
    if f is None:
        return False
    n, _ = _uvar(inner, f.value)
    if n != 0:
        raise NightLightError("Unsupported Night Light state")
    return True


def _read_preview(inner):
    fields, _ = _scan(inner, len(PREFIX))
    f = _one(inner, fields, 70, BOOL, optional=True)
    return f is not None and inner[f.value] != 0


def _strength_to_k(strength):
    return MAX_K - round((MAX_K - MIN_K) * int(strength) / 100)


def _k_to_strength(k):
    return round((MAX_K - k) * 100 / (MAX_K - MIN_K))


class NightLight:
    def __init__(self):
        self._highest = {SETTINGS: 0, STATE: 0}

    @staticmethod
    def _read(kind):
        if winreg is None:
            raise NightLightError("Windows Night Light requires Windows")
        key_path = ROOT + kind + r"\windows.data.bluelightreduction." + kind
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                data, typ = winreg.QueryValueEx(key, "Data")
        except OSError as exc:
            raise NightLightError(f"Windows Night Light {kind} is unavailable: {exc}") from exc
        if typ != winreg.REG_BINARY:
            raise NightLightError("Night Light data is not REG_BINARY")
        return _unpack_record(data)

    def read(self):
        settings, state = self._read(SETTINGS), self._read(STATE)
        return {"strength": _k_to_strength(_read_temp(settings.inner)),
                "enabled": _read_on(state.inner)}

    def _write(self, kind, record, inner):
        stamp = max(int(time.time()), record.stamp + 2, self._highest[kind] + 2)
        data = _repack_record(record, inner, stamp)
        key_path = ROOT + kind + r"\windows.data.bluelightreduction." + kind
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "Data", 0, winreg.REG_BINARY, data)
        except OSError as exc:
            raise NightLightError(f"Cannot write Night Light {kind}: {exc}") from exc
        self._highest[kind] = stamp

    def _write_settings(self, kelvin, preview, only_if_same=None):
        record = self._read(SETTINGS)
        old_temp = _read_temp(record.inner)
        if only_if_same is not None and old_temp != only_if_same:
            return
        if old_temp == kelvin and _read_preview(record.inner) == preview:
            return
        inner = _patch_struct(record.inner[len(PREFIX):], 40, _make(40, INT16, _zigzag(kelvin)))
        inner = _patch_struct(inner, 70, _make(70, BOOL, b"\x01") if preview else None)
        self._write(SETTINGS, record, PREFIX + inner)
        if _read_temp(self._read(SETTINGS).inner) != kelvin:
            raise NightLightError("Windows did not retain Night Light warmth")

    def set_strength(self, strength):
        if not 0 <= int(strength) <= 100:
            raise ValueError("Night Light strength must be 0–100")
        kelvin = _strength_to_k(strength)
        enabled = _read_on(self._read(STATE).inner)
        self._write_settings(kelvin, preview=enabled)
        if enabled:
            try:
                time.sleep(0.07)
            finally:
                # Do not overwrite a different temperature set by Windows meanwhile.
                self._write_settings(kelvin, preview=False, only_if_same=kelvin)

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        record = self._read(STATE)
        if _read_on(record.inner) == enabled:
            return
        inner = _patch_struct(record.inner[len(PREFIX):], 0,
                              _make(0, INT32, _zigzag(0)) if enabled else None)
        inner = _patch_struct(inner, 10, _make(10, INT32, _zigzag(1)))
        filetime = int((time.time() + 11644473600) * 10_000_000)
        inner = _patch_struct(inner, 20, _make(20, UINT64, _packvar(filetime)))
        self._write(STATE, record, PREFIX + inner)
        if _read_on(self._read(STATE).inner) != enabled:
            raise NightLightError("Windows did not retain Night Light on/off state")
