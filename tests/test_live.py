"""The generated command line against the real emulator.

Off unless asked for, because it needs qemu-system-m68k, the ROMs and disk
images, and takes about 20 seconds per machine:

    QEMUGUI_LIVE=1 QEMUGUI_QEMU_DIR=/Applications/Qemu-system-m68k \\
    QEMUGUI_Q800_DISK=/path/system8.0.img QEMUGUI_Q700_DISK=/path/system7.1.img \\
        python -m pytest tests/test_live.py -s

The argv is exactly what the GUI builds, with only three things added for a
headless run: ``-display none`` replaces the window, ``-snapshot`` keeps every
image unchanged (writes go to a temporary overlay), and a QMP socket takes a
screenshot at the end. The PRAM is a blank one in a temporary folder.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from qemugui import command, model  # noqa: E402

QEMU_DIR = os.environ.get("QEMUGUI_QEMU_DIR", "/Applications/Qemu-system-m68k")
RUN_SECONDS = float(os.environ.get("QEMUGUI_LIVE_SECONDS", "20"))
LIVE = os.environ.get("QEMUGUI_LIVE") == "1"
SHOTS = os.environ.get("QEMUGUI_LIVE_SHOTS")       # folder for the screenshots


def headless(argv: list[str], qmp_path: str) -> list[str]:
    out = list(argv)
    i = out.index("-display")
    out[i + 1] = "none"
    return out + ["-snapshot", "-qmp", f"unix:{qmp_path},server=on,wait=off"]


def qmp(path: str, *commands: dict) -> list[dict]:
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(10)
    s.connect(path)
    f = s.makefile("rw")
    replies = [json.loads(f.readline())]                  # greeting
    for c in ({"execute": "qmp_capabilities"},) + commands:
        f.write(json.dumps(c) + "\n")
        f.flush()
        while True:
            reply = json.loads(f.readline())
            if "event" not in reply:
                replies.append(reply)
                break
    s.close()
    return replies


@unittest.skipUnless(LIVE, "set QEMUGUI_LIVE=1 to run the emulator")
class LiveLaunch(unittest.TestCase):

    def run_machine(self, m: model.Machine) -> tuple[int | None, str]:
        with tempfile.TemporaryDirectory() as td:
            lib = model.Library(Path(td) / "Machines")
            folder = lib.save(m)                           # makes the blank pram.img
            self.assertEqual((folder / "pram.img").stat().st_size, model.PRAM_SIZE)
            argv = command.build_argv(m, QEMU_DIR, str(folder))
            qmp_path = str(Path(td) / "qmp.sock")
            full = headless(argv, qmp_path)
            print("\n" + command.one_line(full, str(folder)))
            log = Path(td) / "log.txt"
            with open(log, "w") as fh:
                proc = subprocess.Popen(full, cwd=folder, stdout=fh, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL)
            try:
                deadline = time.time() + RUN_SECONDS
                while time.time() < deadline and proc.poll() is None:
                    time.sleep(0.5)
                rc = proc.poll()
                if rc is None:
                    cmds = [{"execute": "query-status"}]
                    if SHOTS:
                        Path(SHOTS).mkdir(parents=True, exist_ok=True)
                        cmds.append({"execute": "screendump", "arguments": {
                            "filename": str(Path(SHOTS) / f"{m.name}.ppm")}})
                    replies = qmp(qmp_path, *cmds)
                    status = replies[2]["return"]["status"]
                    print(f"{m.name}: alive after {RUN_SECONDS:.0f} s, status {status}")
                    self.assertEqual(status, "running")
                out = log.read_text(errors="replace")     # before we stop it
            finally:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return rc, out if rc is None else log.read_text(errors="replace")

    def machine(self, name: str, mid: str, disk_env: str) -> model.Machine:
        m = model.new_machine(name, mid)
        disk = os.environ.get(disk_env)
        if disk:
            m.scsi.append(model.ScsiDrive(0, "disk", disk, "raw"))
        cd = os.environ.get("QEMUGUI_CD")
        if cd:
            m.scsi.append(model.ScsiDrive(3, "cdrom", cd, "raw"))
        fd = os.environ.get("QEMUGUI_FLOPPY")
        if fd:
            m.floppies[0] = model.Floppy(fd, readonly=True)
        return m

    def check(self, m: model.Machine):
        rc, log = self.run_machine(m)
        self.assertIsNone(rc, f"exited with {rc}:\n{log}")
        self.assertNotIn("qemu-system-m68k:", log, log)

    def test_q800(self):
        self.check(self.machine("live-q800", "q800", "QEMUGUI_Q800_DISK"))

    def test_q700(self):
        self.check(self.machine("live-q700", "q700", "QEMUGUI_Q700_DISK"))

    def test_every_screen(self):
        """Each mode in the tables is accepted by -g (a short run each)."""
        from qemugui import systems
        for mid, screens in systems.SCREENS.items():
            for s in screens:
                with self.subTest(machine=mid, screen=s.id):
                    m = model.new_machine(f"g-{mid}-{s.id}", mid)
                    m.screen = s.id
                    m.icount = False
                    m.pram = ""                          # no PRAM needed here
                    argv = command.build_argv(m, QEMU_DIR, "/tmp")
                    argv[argv.index("-display") + 1] = "none"
                    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True)
                    time.sleep(2)
                    alive = proc.poll() is None
                    proc.kill()
                    out = proc.communicate()[0]
                    self.assertTrue(alive, out)
                    self.assertNotIn("unknown display mode", out)
