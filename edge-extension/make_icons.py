# 生成扩展图标（纯色 PNG，无需 Pillow）
# Run: .venv\Scripts\python edge-extension\make_icons.py

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RGBA = (77, 159, 255, 255)          # #4d9fff


def make_png(path, size, rgba):
    raw = b"".join(b"\x00" + bytes(rgba) * size for _ in range(size))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    hdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", hdr)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))
    path.write_bytes(blob)


for s in (16, 48, 128):
    make_png(ROOT / f"icon{s}.png", s, RGBA)
    print("icon", s, "ok")
