"""TeraDrive v0.1 - mount TeraBox as a Windows drive (READ-ONLY, untested).

Setup:  1) install WinFsp (https://winfsp.dev)
        2) pip install fusepy requests
        3) python terabox_drive.py T        (T = drive letter)
Login uses your browser's 'ndus' cookie (terabox.com > DevTools > Application >
Cookies). Treat it like a password and use a test account.
Unofficial web endpoints: they may differ or change; errors are printed in full.
"""
import errno
import json
import os
import stat
import sys
import time

import requests

BASE = "https://www.terabox.com"
COMMON = {"app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


class TeraBox:
    def __init__(self, ndus):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.s.cookies.set("ndus", ndus, domain=".terabox.com")
        self.dirs = {}    # path -> (time, entries)
        self.links = {}   # path -> (time, dlink)

    def _get(self, path, **params):
        r = self.s.get(BASE + path, params={**COMMON, **params}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("errno", 0) != 0:
            raise RuntimeError("%s errno=%s body=%s" % (path, data.get("errno"), data))
        return data

    def listdir(self, d):
        hit = self.dirs.get(d)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        items, page = [], 1
        while True:
            data = self._get("/api/list", dir=d, num=1000, page=page, order="name", desc=0)
            batch = data.get("list", [])
            items += batch
            if len(batch) < 1000:
                break
            page += 1
        self.dirs[d] = (time.time(), items)
        return items

    def dlink(self, path):
        hit = self.links.get(path)
        if hit and time.time() - hit[0] < 300:
            return hit[1]
        data = self._get("/api/filemetas", target=json.dumps([path]), dlink=1)
        link = data["info"][0]["dlink"]
        self.links[path] = (time.time(), link)
        return link

    def read(self, path, size, offset):
        r = self.s.get(self.dlink(path), timeout=60,
                       headers={"Range": "bytes=%d-%d" % (offset, offset + size - 1)})
        r.raise_for_status()
        return r.content


def build_fs(tb, FuseOSError, Operations):
    class TeraFS(Operations):
        def _entry(self, path):
            if path == "/":
                return {"isdir": 1, "size": 0, "server_mtime": int(time.time())}
            parent, name = path.rsplit("/", 1)
            for e in tb.listdir(parent or "/"):
                if e["server_filename"] == name:
                    return e
            raise FuseOSError(errno.ENOENT)

        def getattr(self, path, fh=None):
            e = self._entry(path)
            t = int(e.get("server_mtime", time.time()))
            isdir = bool(e["isdir"])
            return {"st_mode": (stat.S_IFDIR | 0o755) if isdir else (stat.S_IFREG | 0o444),
                    "st_nlink": 2 if isdir else 1, "st_size": int(e.get("size", 0)),
                    "st_atime": t, "st_mtime": t, "st_ctime": t, "st_uid": 0, "st_gid": 0}

        def readdir(self, path, fh):
            return [".", ".."] + [e["server_filename"] for e in tb.listdir(path)]

        def read(self, path, size, offset, fh):
            size = min(size, max(0, int(self._entry(path)["size"]) - offset))
            return tb.read(path, size, offset) if size > 0 else b""

    return TeraFS()


def main():
    ndus = os.environ.get("TERABOX_NDUS") or input("ndus cookie: ").strip()
    letter = (sys.argv[1] if len(sys.argv) > 1 else "T").strip(":").upper() + ":"
    os.environ.setdefault("FUSE_LIBRARY_PATH",
                          r"C:\Program Files (x86)\WinFsp\bin\winfsp-x64.dll")
    from fuse import FUSE, FuseOSError, Operations  # import after env var is set

    tb = TeraBox(ndus)
    root = tb.listdir("/")  # login check: prints the real error if it fails
    print("Login OK, %d items in root. Mounting on %s ..." % (len(root), letter))
    FUSE(build_fs(tb, FuseOSError, Operations), letter, foreground=True, ro=True)


if __name__ == "__main__":
    main()
