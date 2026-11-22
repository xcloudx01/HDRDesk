"""Filter a Procmon CSV export down to writes / IOCTLs from NVIDIA processes."""
import collections
import csv
import re
import sys

src = sys.argv[1]
NV = re.compile(r"nv|nvidia", re.I)
WRITE_OPS = {"RegSetValue", "RegCreateKey", "RegDeleteValue", "RegDeleteKey", "RegSetInfoKey", "WriteFile",
             "SetRenameInformationFile", "SetDispositionInformationFile", "SetBasicInformationFile",
             "DeviceIoControl", "FileSystemControl"}
NOISE = re.compile(r"CefCache|\\Logs?\\|\.log$|DXCache|\\Temp\\|ShadowPlay|FrameView|MessageBus|\\Prefetch\\", re.I)

counts = collections.Counter()
rows = []
with open(src, encoding="utf-8-sig", errors="replace", newline="") as f:
    for r in csv.DictReader(f):
        proc, op, path = r["Process Name"], r["Operation"], r["Path"]
        if not NV.search(proc) or op not in WRITE_OPS or NOISE.search(path):
            continue
        key = (proc, op, re.sub(r"\d{3,}", "#", path))
        counts[key] += 1
        if counts[key] <= 3:
            rows.append((r["Time of Day"][:12], proc, r["PID"], op, path, r["Result"], r["Detail"][:160]))

print("=== distinct (process, op, path) with counts ===")
for (proc, op, path), n in sorted(counts.items(), key=lambda kv: (kv[0][1], -kv[1])):
    print(f"{n:6}  {proc:22} {op:18} {path[:170]}")
print("\n=== first occurrences ===")
for row in rows:
    if row[3] != "DeviceIoControl":
        print(" | ".join(row))
