"""Minimal in-memory fake for xbmcvfs. Expands as features land."""
import os
import io
import time
from typing import Dict


class _Stat:
    def __init__(self, size: int, ino: int = 0, mtime: float = 0):
        self._size = size
        self._ino = ino
        self._mtime = mtime
    def st_size(self): return self._size
    def st_mtime(self): return self._mtime
    def st_ino(self): return self._ino


_files: Dict[str, bytes] = {}
_special_map = {
    "special://profile/": "/tmp/kodi-ai-test/profile/",
    "special://userdata/": "/tmp/kodi-ai-test/userdata/",
    "special://temp/": "/tmp/kodi-ai-test/temp/",
    "special://logpath/": "/tmp/kodi-ai-test/logpath/",
    "special://home/": "/tmp/kodi-ai-test/home/",
}


def translatePath(path: str) -> str:
    for prefix, real in _special_map.items():
        if path.startswith(prefix):
            return real + path[len(prefix):]
    return path


def Stat(path: str) -> _Stat:
    real = translatePath(path)
    if not os.path.exists(real):
        raise FileNotFoundError(real)
    st = os.stat(real)
    return _Stat(st.st_size, getattr(st, "st_ino", 0), st.st_mtime)


def exists(path: str) -> bool:
    return os.path.exists(translatePath(path))


def mkdirs(path: str) -> bool:
    os.makedirs(translatePath(path), exist_ok=True)
    return True


def delete(path: str) -> bool:
    real = translatePath(path)
    if os.path.isfile(real):
        os.remove(real)
        return True
    return False


def listdir(path: str):
    real = translatePath(path)
    if not os.path.isdir(real):
        return ([], [])
    entries = os.listdir(real)
    dirs = [e for e in entries if os.path.isdir(os.path.join(real, e))]
    files = [e for e in entries if os.path.isfile(os.path.join(real, e))]
    return (dirs, files)


class File:
    def __init__(self, path: str, mode: str = "r"):
        self._real = translatePath(path)
        self._mode = mode
        if "r" in mode:
            if not os.path.exists(self._real):
                raise FileNotFoundError(self._real)
            self._fp = open(self._real, "rb")
        elif "w" in mode:
            os.makedirs(os.path.dirname(self._real), exist_ok=True)
            self._fp = open(self._real, "wb")
        else:
            raise ValueError(mode)
    def read(self, n: int = -1) -> bytes:
        return self._fp.read(n)
    def seek(self, offset: int, whence: int = 0):
        return self._fp.seek(offset, whence)
    def write(self, data) -> bool:
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._fp.write(data); return True
    def close(self):
        self._fp.close()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def reset_test_fs():
    """Wipe the test FS root. Call from pytest fixtures."""
    import shutil
    if os.path.exists("/tmp/kodi-ai-test"):
        shutil.rmtree("/tmp/kodi-ai-test")
