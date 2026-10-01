"""
Pack the raw API cache into archives, and unpack it again.

The cache under data/raw/ holds ~254,000 small JSON files (~0.9 GB of content).
On a drive with large allocation units each file occupies at least 128 KB, so
the loose cache takes ~32 GB of disk. Packed into one zip per folder it takes a
fraction of that and preserves the frozen observation byte for byte.

    python pack_cache.py pack      # zip, verify every file, then delete the loose copies
    python pack_cache.py unpack    # restore the loose files before re-running the pipeline

Packing deletes a folder only after its archive has been re-read and every
member's CRC checked and the member count matched to the files on disk.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

import config

FOLDERS = ("life_history", "api_cache")


def pack(name: str) -> None:
    src = config.DATA_RAW / name
    dst = config.DATA_RAW / f"{name}.zip"
    if not src.exists():
        print(f"{name}: no loose folder, nothing to pack")
        return
    files = [p for p in src.rglob("*") if p.is_file()]
    print(f"{name}: packing {len(files):,} files")
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, p in enumerate(files, 1):
            z.write(p, p.relative_to(config.DATA_RAW).as_posix())
            if i % 25_000 == 0:
                print(f"  {i:,} written")
    with zipfile.ZipFile(dst) as z:
        bad = z.testzip()
        n = len(z.infolist())
    if bad is not None or n != len(files):
        sys.exit(f"{name}: verification FAILED (bad member {bad}, {n} vs {len(files)}); loose files kept")
    print(f"{name}: verified {n:,} members, {dst.stat().st_size / 1e6:,.0f} MB; removing loose files")
    shutil.rmtree(src)


def unpack(name: str) -> None:
    arc = config.DATA_RAW / f"{name}.zip"
    if not arc.exists():
        print(f"{name}: no archive")
        return
    with zipfile.ZipFile(arc) as z:
        z.extractall(config.DATA_RAW)
    print(f"{name}: unpacked")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ("pack", "unpack"):
        sys.exit(__doc__)
    for folder in FOLDERS:
        (pack if action == "pack" else unpack)(folder)
