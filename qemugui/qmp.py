"""Talk to a running emulator over its control connection (QMP, QEMU's
machine protocol): put a floppy disk into a drive, take one out, and see
which disks QEMU has in its drives.

Each machine is started with ``-qmp tcp:127.0.0.1:PORT`` (command.py), so
this works whatever window QEMU shows (Cocoa, SDL, GTK) and on every host,
also for a run started in Terminal.

What QEMU reports is its own side: a disk the Mac has ejected (dragged to
the Trash) is still "in the drive" for QEMU until another one goes in.
"""

from __future__ import annotations

import json
import os
import socket

TIMEOUT = 3.0


class QMPError(Exception):
    """The emulator could not be reached, or it refused the request."""


def _command(f, msg: dict):
    f.write(json.dumps(msg) + "\n")
    f.flush()
    while True:
        line = f.readline()
        if not line:
            raise QMPError("The emulator closed the connection.")
        reply = json.loads(line)
        if "event" in reply:
            continue
        if "error" in reply:
            raise QMPError(reply["error"].get("desc", "The emulator refused it."))
        return reply.get("return")


def execute(port: int, command: str, arguments: dict | None = None,
            timeout: float = TIMEOUT):
    """Run one QMP command; returns its result."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            f = s.makefile("rw", encoding="utf-8", newline="\n")
            greeting = json.loads(f.readline() or "{}")
            if "QMP" not in greeting:
                raise QMPError("Something else answers on that port.")
            _command(f, {"execute": "qmp_capabilities"})
            msg = {"execute": command}
            if arguments:
                msg["arguments"] = arguments
            return _command(f, msg)
    except (OSError, ValueError) as e:
        raise QMPError(f"The emulator cannot be reached ({e}).") from e


def drive_id(index: int) -> str:
    """QEMU's name for floppy drive *index* (0 = internal)."""
    return f"floppy{index}"


def insert_floppy(port: int, index: int, path: str, readonly: bool = False):
    """Put the disk image *path* into drive *index*, taking out whatever is
    in it. Read only: the Mac sees a locked disk."""
    execute(port, "blockdev-change-medium",
            {"device": drive_id(index), "filename": os.path.abspath(path),
             "format": "raw",
             "read-only-mode": "read-only" if readonly else "read-write"})


def eject_floppy(port: int, index: int):
    execute(port, "eject", {"device": drive_id(index), "force": True})


def floppy_files(port: int) -> dict[int, str | None]:
    """The image in each floppy drive as QEMU sees it (None: empty)."""
    out: dict[int, str | None] = {}
    for dev in execute(port, "query-block") or []:
        name = dev.get("device", "")
        if name.startswith("floppy") and name[6:].isdigit():
            inserted = dev.get("inserted")
            # a "Read only" disk from the start is a temporary overlay
            # (snapshot=on) on top of the image: show the image
            out[int(name[6:])] = ((inserted.get("backing_file") or inserted.get("file"))
                                  if inserted else None)
    return out
