"""Find escapes whose input buffer contains given DWORD values; summarise traffic."""
import collections
import json
import struct
import sys

path = sys.argv[1]
needles = [int(x) for x in sys.argv[2:]]
recs = [json.loads(line) for line in open(path)]
esc = [r for r in recs if r.get("k") == "esc"]
print("escapes:", len(esc), " qi:", [(r["pid"], r["id"]) for r in recs if r.get("k") == "qi"][:40])
print("by (pid,type,size):", collections.Counter((r["pid"], r["type"], r["size"]) for r in esc).most_common(15))


def dwords_at(buf, val):
    pat = struct.pack("<I", val)
    return [i for i in range(0, len(buf) - 3) if buf[i:i + 4] == pat]


for n in needles:
    print(f"\n===== escapes containing DWORD {n} ({n:#x}) in INPUT =====")
    for r in esc:
        b = bytes.fromhex(r["hex"])
        inp, out = b[:r["size"]], b[r["size"]:]
        hits = dwords_at(inp, n)
        if hits:
            print(f"t={r['t']} pid={r['pid']} tid={r['tid']} hA={r['hA']:#x} type={r['type']} flags={r['flags']:#x} "
                  f"size={r['size']} ret={r['ret']:#x} offsets={hits[:8]}")
            print("  in :", inp[:min(len(inp), 160)].hex(" ", 4))
            if out != inp:
                print("  out:", out[:min(len(out), 160)].hex(" ", 4))
