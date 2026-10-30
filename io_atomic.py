# -*- coding: utf-8 -*-
# io_atomic.py — D18: atomic JSON writes + corrupt-file fallback + exclusive write lock
# Writers: write temp file in the same dir, fsync, then os.replace() under an
#          exclusive lock file so two writers never interleave on one path.
# Readers: skip unreadable/corrupt files newest->older and fall back to the
#          previous valid file.
import contextlib
import json
import os
import tempfile
import time

LOCK_STALE_SEC = 900  # a .lock older than this is considered abandoned and stolen


@contextlib.contextmanager
def exclusive_lock(path, timeout=60.0, stale_sec=LOCK_STALE_SEC):
    """# D18 portable O_EXCL spin-lock: two writers never run at once on one path."""
    lock_path = str(path) + ".lock"
    t0 = time.time()
    fd = None
    taken = False
    try:
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                taken = True
                break
            except FileExistsError:
                pass
            except OSError:
                pass
            try:
                if time.time() - os.path.getmtime(lock_path) > stale_sec:
                    os.remove(lock_path)  # steal abandoned lock
                    continue
            except OSError:
                pass
            if time.time() - t0 > timeout:
                raise TimeoutError("D18 exclusive_lock timeout: %s" % lock_path)
            time.sleep(0.02)
        yield lock_path
    finally:
        if taken:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.remove(lock_path)
            except OSError:
                pass


def atomic_write_json(path, data, indent=2):
    """# D18 write temp file then os.replace() — readers never see partial/corrupt."""
    path = str(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        with exclusive_lock(path):
            os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_json(path):
    """Return (data, error). data is None when missing/unreadable/corrupt."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return None, e


def load_newest_valid(files, on_error=None):
    """# D18 readers: skip unreadable files and fall back to the previous valid file.

    files: iterable of existing paths. Returns (path, data); (None, None) when
    every candidate is unreadable and directory has no valid file at all."""
    for p in sorted(files, reverse=True):
        data, err = read_json(p)
        if data is not None:
            return p, data
        if on_error is not None:
            try:
                on_error(p, err)
            except Exception:
                pass
    return None, None
