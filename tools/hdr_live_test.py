"""Elevated test: alternate one RTX Video HDR setting to see if the driver reacts live.
usage: hdr_live_test.py <key> <valA> <valB> <restore> [cycles] [period_s] [<key2> <a> <b> <restore>]"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nvhdr  # noqa: E402

log = open(os.path.join(os.environ["TEMP"], "hdr_live_test.log"), "w")


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, file=log, flush=True)


def alternate(key, a, b, restore, cycles, period):
    for i in range(cycles):
        v = a if i % 2 == 0 else b
        nvhdr.write({key: v})
        say(f"{key}={v} readback={nvhdr.read()[key]}")
        time.sleep(period)
    nvhdr.write({key: restore})
    say(f"{key} restored to {restore}")


try:
    args = sys.argv[1:]
    say("admin:", nvhdr.is_admin(), "start:", nvhdr.read())
    time.sleep(3)
    key, a, b, r = args[0], int(args[1]), int(args[2]), int(args[3])
    cycles = int(args[4]) if len(args) > 4 else 6
    period = float(args[5]) if len(args) > 5 else 3
    alternate(key, a, b, r, cycles, period)
    if len(args) > 6:
        time.sleep(2)
        alternate(args[6], int(args[7]), int(args[8]), int(args[9]), cycles, period)
    say("final:", nvhdr.read())
except Exception as e:
    say("ERROR:", repr(e))
