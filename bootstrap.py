"""
bootstrap.py - run this before importing anything from core/.

Python decides a cached .pyc is still good by comparing the source file's
recorded mtime and size. That is a sound assumption on a local disk and a bad
one for this project: the folder gets copied between machines, edited through
file shares and sync clients, handed out on USB sticks and unpacked from zips,
any of which can leave a source file newer in content but not in metadata.

When that happens Python silently runs yesterday's code. The symptom is
genuinely maddening to debug, because every obvious explanation is wrong: an
edit that is plainly in the file has no effect, restarting changes nothing,
and the program prints messages whose text does not exist anywhere in the
source tree. It cost an afternoon on 8 Oct 2026 - a corrected model name in
config.json kept coming back as the old one, and the actual cause was a .pyc
from an earlier run.

Recompiling this project from scratch costs a few hundred milliseconds. One
stale import costs an hour. So CastleKeep never caches bytecode at all.
"""

import os
import sys


def purge(root):
    sys.dont_write_bytecode = True
    removed = 0
    for dirpath, dirnames, _ in os.walk(root):
        if "node_modules" in dirpath:
            dirnames[:] = []
            continue
        if "__pycache__" not in dirnames:
            continue
        dirnames.remove("__pycache__")
        full = os.path.join(dirpath, "__pycache__")
        try:
            for name in os.listdir(full):
                os.remove(os.path.join(full, name))
                removed += 1
            os.rmdir(full)
        except OSError:
            # Locked by another running interpreter, or read-only media.
            # Not fatal: dont_write_bytecode still stops us making it worse,
            # and a locked .pyc is usually one this very process will ignore.
            pass
    return removed
