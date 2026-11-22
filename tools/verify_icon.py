"""Verify the exact Windows ICO frames are embedded in the packaged EXE."""
import struct
import sys
from pathlib import Path

import pefile


def main():
    source, executable = map(Path, sys.argv[1:])
    ico = source.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", ico)
    assert (reserved, kind) == (0, 1)
    frames = {}
    for index in range(count):
        width, height, _, _, planes, bits, size, offset = struct.unpack_from(
            "<BBBBHHII", ico, 6 + 16 * index
        )
        width, height = width or 256, height or 256
        assert width == height and planes == 1 and bits == 32
        assert offset + size <= len(ico)
        frames[width] = ico[offset:offset + size]
    assert set(frames) == {16, 24, 32, 48, 64, 128, 256}
    pe = pefile.PE(str(executable))
    resources = {e.id: e for e in pe.DIRECTORY_ENTRY_RESOURCE.entries}
    assert 3 in resources and 14 in resources, "Missing RT_ICON or RT_GROUP_ICON"
    images = []
    for entry in resources[3].directory.entries:
        for lang in entry.directory.entries:
            data = lang.data.struct
            images.append(pe.get_data(data.OffsetToData, data.Size))
    for size, frame in frames.items():
        assert frame in images, f"Missing exact {size}px icon frame in executable"
    print("Verified all seven embedded icon sizes:", sorted(frames))


if __name__ == "__main__":
    main()
