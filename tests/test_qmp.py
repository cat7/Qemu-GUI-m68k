"""The control connection (qemugui.qmp) against a stand-in QMP server."""

from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from qemugui import qmp  # noqa: E402
from fake_qmp import FakeQMP  # noqa: E402


class Floppies(unittest.TestCase):
    def setUp(self):
        self.q = FakeQMP()

    def tearDown(self):
        self.q.close()

    def test_insert_and_eject(self):
        self.assertEqual(qmp.floppy_files(self.q.port), {0: None, 1: None})
        qmp.insert_floppy(self.q.port, 1, "/fd/Install 2.img", readonly=True)
        self.assertEqual(qmp.floppy_files(self.q.port), {0: None, 1: "/fd/Install 2.img"})
        sent = [c for c in self.q.commands if c["execute"] == "blockdev-change-medium"][-1]
        self.assertEqual(sent["arguments"], {"device": "floppy1", "filename": "/fd/Install 2.img",
                                             "format": "raw", "read-only-mode": "read-only"})
        qmp.eject_floppy(self.q.port, 1)
        self.assertEqual(qmp.floppy_files(self.q.port)[1], None)

    def test_read_write_by_default(self):
        qmp.insert_floppy(self.q.port, 0, "/fd/a.img")
        self.assertFalse(self.q.drives["floppy0"]["ro"])

    def test_a_refusal_is_an_error(self):
        with self.assertRaises(qmp.QMPError) as cm:
            qmp.insert_floppy(self.q.port, 5, "/fd/a.img")
        self.assertIn("not found", str(cm.exception))

    def test_nobody_listening(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with self.assertRaises(qmp.QMPError):
            qmp.floppy_files(port)

    def test_snapshot_disk_shows_the_image(self):
        self.q.drives["floppy0"] = {"file": "/tmp/vl.ABC", "backing_file": "/fd/Disk Tools.img"}
        self.assertEqual(qmp.floppy_files(self.q.port)[0], "/fd/Disk Tools.img")


if __name__ == "__main__":
    unittest.main()
