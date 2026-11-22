"""Elevated: attach escape_hook.js to all NVIDIA service processes for N seconds, log to trace\\escapes.jsonl."""
import json
import os
import sys
import time

import ctypes
from ctypes import wintypes as W

import frida


def enable_debug_privilege():
    """SYSTEM-owned NVIDIA services only open with SeDebugPrivilege enabled (verified by procaccess.py)."""
    k32, adv = ctypes.WinDLL("kernel32"), ctypes.WinDLL("advapi32")
    k32.GetCurrentProcess.restype = W.HANDLE
    adv.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
    adv.AdjustTokenPrivileges.argtypes = [W.HANDLE, W.BOOL, ctypes.c_void_p, W.DWORD, ctypes.c_void_p, ctypes.c_void_p]

    class LUID(ctypes.Structure):
        _fields_ = [("Low", W.DWORD), ("High", W.LONG)]

    class TP(ctypes.Structure):
        _fields_ = [("Count", W.DWORD), ("Luid", LUID), ("Attr", W.DWORD)]

    tok, luid = W.HANDLE(), LUID()
    adv.OpenProcessToken(k32.GetCurrentProcess(), 0x28, ctypes.byref(tok))
    adv.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid))
    adv.AdjustTokenPrivileges(tok, False, ctypes.byref(TP(1, luid, 2)), 0, None, None)


enable_debug_privilege()

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "trace")
os.makedirs(OUT, exist_ok=True)
duration = float(sys.argv[1]) if len(sys.argv) > 1 else 75
log = open(os.path.join(OUT, "escapes.jsonl"), "w")
status = open(os.path.join(OUT, "escape_status.txt"), "w")
src = open(os.path.join(HERE, "escape_hook.js")).read()

class P:
    def __init__(self, pid, name):
        self.pid, self.name = pid, name


dev = frida.get_local_device()
sessions = []
if len(sys.argv) > 2:  # explicit PIDs (SYSTEM services don't show up in enumerate_processes)
    targets = [P(int(x), f"pid{x}") for x in sys.argv[2:]]
else:
    targets = [p for p in dev.enumerate_processes() if p.name.lower() in ("nvcontainer.exe", "nvdisplay.container.exe")]
for p in targets:
    if True:
        try:
            s = dev.attach(p.pid)
            sc = s.create_script(src)

            def on_msg(msg, data, pid=p.pid, name=p.name):
                if msg["type"] == "send":
                    rec = {"pid": pid, "proc": name, **msg["payload"]}
                    if data:
                        rec["hex"] = data.hex()
                    log.write(json.dumps(rec) + "\n")
                else:
                    log.write(json.dumps({"pid": pid, "error": msg.get("description")}) + "\n")
                log.flush()

            sc.on("message", on_msg)
            sc.load()
            sessions.append(s)
            print("attached", p.pid, p.name, file=status, flush=True)
        except Exception as e:
            print("FAILED", p.pid, p.name, repr(e), file=status, flush=True)

print("start", time.strftime("%H:%M:%S"), file=status, flush=True)
time.sleep(duration)
for s in sessions:
    try:
        s.detach()
    except Exception:
        pass
print("end", time.strftime("%H:%M:%S"), file=status, flush=True)
