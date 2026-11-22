"""Snapshot NVIDIA-related registry trees to JSON, or diff two snapshots.
usage: regsnap.py snap out.json | regsnap.py diff a.json b.json | regsnap.py grep <regex>"""
import json
import re
import sys
import winreg as R

ROOTS = [
    (R.HKEY_CURRENT_USER, r"Software\NVIDIA Corporation"),
    (R.HKEY_LOCAL_MACHINE, r"SOFTWARE\NVIDIA Corporation"),
    (R.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\nvlddmkm"),
    (R.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"),
    (R.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers"),
    (R.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\VideoSettings"),
    (R.HKEY_CURRENT_USER, r"Software\Microsoft\DirectX"),
]
HNAME = {R.HKEY_CURRENT_USER: "HKCU", R.HKEY_LOCAL_MACHINE: "HKLM"}


def walk(hive, path, out):
    try:
        k = R.OpenKey(hive, path, 0, R.KEY_READ | R.KEY_WOW64_64KEY)
    except OSError:
        return
    with k:
        i = 0
        while True:
            try:
                name, val, typ = R.EnumValue(k, i)
            except OSError:
                break
            if isinstance(val, bytes):
                val = val.hex()
            out[f"{HNAME[hive]}\\{path}\\{name}"] = repr(val)
            i += 1
        i = 0
        while True:
            try:
                sub = R.EnumKey(k, i)
            except OSError:
                break
            walk(hive, f"{path}\\{sub}", out)
            i += 1


def snap():
    out = {}
    for h, p in ROOTS:
        walk(h, p, out)
    return out


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "snap":
        with open(sys.argv[2], "w") as f:
            json.dump(snap(), f)
    elif cmd == "diff":
        a, b = (json.load(open(p)) for p in sys.argv[2:4])
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                print(f"{k}\n   {str(a.get(k))[:200]}\n-> {str(b.get(k))[:200]}")
    elif cmd == "grep":
        rx = re.compile(sys.argv[2], re.I)
        for k, v in snap().items():
            if rx.search(k):
                print(k, "=", v[:120])
