"""A stand-in for QEMU's QMP server, enough for the floppy commands."""

from __future__ import annotations

import json
import socket
import threading


class FakeQMP:
    """Listens on a free local port; answers one connection at a time and
    keeps the floppy drives' images like QEMU would."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.drives: dict[str, dict | None] = {"floppy0": None, "floppy1": None}
        self.commands: list[dict] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self):
        self.sock.close()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                f = conn.makefile("rw", encoding="utf-8", newline="\n")
                f.write(json.dumps({"QMP": {"version": {}, "capabilities": []}}) + "\n")
                f.flush()
                for line in f:
                    msg = json.loads(line)
                    self.commands.append(msg)
                    # an event first, as QEMU sends them whenever it likes
                    f.write(json.dumps({"event": "DEVICE_TRAY_MOVED"}) + "\n")
                    f.write(json.dumps(self._answer(msg)) + "\n")
                    f.flush()

    def _answer(self, msg: dict) -> dict:
        cmd, args = msg["execute"], msg.get("arguments", {})
        if cmd == "qmp_capabilities":
            return {"return": {}}
        if cmd == "query-block":
            return {"return": [{"device": d, "inserted": ins} if ins else {"device": d}
                               for d, ins in self.drives.items()]}
        if cmd == "blockdev-change-medium":
            if args["device"] not in self.drives:
                return {"error": {"class": "GenericError",
                                  "desc": f"Device '{args['device']}' not found"}}
            self.drives[args["device"]] = {"file": args["filename"],
                                           "ro": args["read-only-mode"] == "read-only"}
            return {"return": {}}
        if cmd == "eject":
            self.drives[args["device"]] = None
            return {"return": {}}
        return {"error": {"class": "CommandNotFound", "desc": cmd}}
