"""Elevated diag: enable SeDebugPrivilege, then report open-access + protection level for given PIDs."""
import ctypes
import os
import sys
from ctypes import wintypes as W

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
adv = ctypes.WinDLL("advapi32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
out = open(os.path.join(os.environ["TEMP"], "procaccess.txt"), "w")


class LUID(ctypes.Structure):
    _fields_ = [("Low", W.DWORD), ("High", W.LONG)]


class TP(ctypes.Structure):
    _fields_ = [("Count", W.DWORD), ("Luid", LUID), ("Attr", W.DWORD)]


k32.GetCurrentProcess.restype = W.HANDLE
adv.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
adv.AdjustTokenPrivileges.argtypes = [W.HANDLE, W.BOOL, ctypes.c_void_p, W.DWORD, ctypes.c_void_p, ctypes.c_void_p]


def enable_debug():
    tok = W.HANDLE()
    adv.OpenProcessToken(k32.GetCurrentProcess(), 0x28, ctypes.byref(tok))
    luid = LUID()
    adv.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid))
    tp = TP(1, luid, 2)
    adv.AdjustTokenPrivileges(tok, False, ctypes.byref(tp), 0, None, None)
    return ctypes.get_last_error()


k32.OpenProcess.restype = W.HANDLE
print("debug priv err:", enable_debug(), file=out)
for pid in map(int, sys.argv[1:]):
    res = []
    for name, acc in (("ALL", 0x1FFFFF), ("VM_RW+CREATE_THREAD", 0x0002 | 0x0008 | 0x0010 | 0x0020 | 0x0400),
                      ("QUERY_LIMITED", 0x1000)):
        h = k32.OpenProcess(acc, False, pid)
        res.append(f"{name}={'ok' if h else 'err' + str(ctypes.get_last_error())}")
        if h and name == "QUERY_LIMITED":
            prot = ctypes.c_ubyte()
            st = ntdll.NtQueryInformationProcess(W.HANDLE(h), 61, ctypes.byref(prot), 1, None)
            res.append(f"protection=0x{prot.value:02x} (st={st & 0xffffffff:#x})")
        if h:
            k32.CloseHandle(W.HANDLE(h))
    print(pid, " ".join(res), file=out, flush=True)
