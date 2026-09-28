"""Follow a growing log file by byte offset, surviving truncation and rotation."""

from __future__ import annotations

import os

MAX_READ = 1_000_000


class FileTailer:
    def __init__(self, path: str, offset: int = 0, inode: int | None = None) -> None:
        self.path = path
        self.offset = offset
        self.inode = inode

    def read_lines(self) -> list[str]:
        """Return complete new lines; a partial last line waits for its newline."""
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return []
        if (self.inode is not None and st.st_ino != self.inode) or st.st_size < self.offset:
            self.offset = 0  # rotated or truncated: start the new file from the top
        self.inode = st.st_ino
        if st.st_size == self.offset:
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read(MAX_READ)
        end = chunk.rfind(b"\n")
        if end == -1:
            return []
        data = chunk[: end + 1]
        self.offset += len(data)
        return [raw.decode("utf-8", "replace") for raw in data.split(b"\n")[:-1]]
