"""
Read selected members out of a very large remote ZIP without downloading it.

The Companies House "Accounts Monthly Data" archives are 1.5 to 2.4 GB each,
and the study needs roughly 104 of them -- about 200 GB if downloaded whole.
Of each archive, only the few thousand files belonging to cohort companies are
wanted: well under 1% of the bytes.

A ZIP file's index (the central directory) sits at the END of the file, and
every member records its own byte offset. So if the server supports HTTP range
requests -- Companies House does, verified 2026-08-16, it answers 206 Partial
Content -- the whole archive can be treated as a seekable file and Python's
own `zipfile` module will read just the pieces asked for.

In practice: reading the index of a 1.47 GB archive with 207,449 members costs
about 22 MB and two seconds. Each member then costs its own compressed size,
typically 7 KB. The saving over downloading the archives is roughly fifty to
one, which is the difference between a job that runs on a laptop overnight and
one that does not run at all.

If a mirror ever stops honouring range requests, `download_whole` is the
fallback and the pipeline still works; it is just slower and needs the disk.
"""

from __future__ import annotations

import io
import config
import time
import urllib.error
import urllib.request


class HttpRangeFile(io.RawIOBase):
    """A seekable read-only file backed by HTTP range requests.

    Wrap in `io.BufferedReader` before handing to `zipfile.ZipFile`: the
    buffering turns the many small reads the ZIP parser makes into a few large
    range requests, which is the difference between fast and unusable.
    """

    def __init__(self, url: str, timeout: int = 90, max_retries: int = 4):
        self.url = url
        self.timeout = timeout
        self.max_retries = max_retries
        self.pos = 0
        self.bytes_fetched = 0
        self.requests = 0
        self.size = self._head_size()

    def _head_size(self) -> int:
        req = urllib.request.Request(self.url, method="HEAD")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return int(r.headers["Content-Length"])

    # -- io plumbing -------------------------------------------------------

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self.pos = offset
        elif whence == io.SEEK_CUR:
            self.pos += offset
        else:
            self.pos = self.size + offset
        return self.pos

    def readinto(self, buffer) -> int:
        want = len(buffer)
        if want == 0 or self.pos >= self.size:
            return 0
        end = min(self.pos + want, self.size) - 1

        delay = 2.0
        for attempt in range(self.max_retries):
            req = urllib.request.Request(
                self.url,
                headers={
                    "Range": f"bytes={self.pos}-{end}",
                    "User-Agent": (
                        config.USER_AGENT
                    ),
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = r.read()
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(delay)
                delay *= 2
        else:  # pragma: no cover
            return 0

        buffer[: len(data)] = data
        self.pos += len(data)
        self.bytes_fetched += len(data)
        self.requests += 1
        return len(data)


def open_remote_zip(url: str, buffer_size: int = 1 << 21):
    """Return (ZipFile, HttpRangeFile) for a remote archive.

    The second element is returned so callers can report how many bytes the
    run actually cost, which belongs in the methodology note.
    """
    import zipfile

    backing = HttpRangeFile(url)
    return zipfile.ZipFile(io.BufferedReader(backing, buffer_size=buffer_size)), backing


def fetch_members(
    url: str,
    infos: list,
    backing: HttpRangeFile,
    gap_tolerance: int = 1 << 18,
):
    """Yield (ZipInfo, bytes) for the given members, fetching them efficiently.

    Reading members through `zipfile` over a buffered range-reader works, but
    wastes enormous bandwidth: the buffer refills with a full block for every
    random seek, and the wanted members are scattered through an archive of
    200,000 files. Measured on the January 2018 archive, pulling 978 members
    that way cost 756 MB -- over 100 times their actual size.

    This reads them directly instead. Members are sorted by their byte offset
    so access is forward-only, and members that sit within `gap_tolerance` of
    each other are collected in a single range request, since one request for
    a slightly larger contiguous block beats several small ones. The local file
    header is parsed by hand and the payload inflated with zlib.

    Same 978 members, same archive: about 8 MB.
    """
    import struct
    import zlib

    if not infos:
        return

    ordered = sorted(infos, key=lambda i: i.header_offset)

    def member_end(info) -> int:
        # 30-byte local header + name + extra + payload, plus slack for a
        # local extra field longer than the central directory's copy.
        return (
            info.header_offset
            + 30
            + len(info.filename.encode("utf-8"))
            + len(info.extra or b"")
            + info.compress_size
            + 4096
        )

    groups: list[list] = [[ordered[0]]]
    for info in ordered[1:]:
        if info.header_offset - member_end(groups[-1][-1]) <= gap_tolerance:
            groups[-1].append(info)
        else:
            groups.append([info])

    for group in groups:
        start = group[0].header_offset
        end = min(member_end(group[-1]), backing.size) - 1
        backing.seek(start)
        blob = bytearray(end - start + 1)
        got = 0
        while got < len(blob):
            view = memoryview(blob)[got:]
            n = backing.readinto(view)
            if not n:
                break
            got += n
        blob = bytes(blob[:got])

        for info in group:
            base = info.header_offset - start
            if base + 30 > len(blob) or blob[base: base + 4] != b"PK\x03\x04":
                continue
            name_len, extra_len = struct.unpack("<HH", blob[base + 26: base + 30])
            data_start = base + 30 + name_len + extra_len
            payload = blob[data_start: data_start + info.compress_size]
            if len(payload) < info.compress_size:
                continue
            try:
                if info.compress_type == 0:
                    content = payload
                else:
                    content = zlib.decompressobj(-15).decompress(payload)
            except zlib.error:
                continue
            yield info, content


def download_whole(url: str, dest) -> None:
    """Fallback: fetch the entire archive to disk."""
    with urllib.request.urlopen(url, timeout=600) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
