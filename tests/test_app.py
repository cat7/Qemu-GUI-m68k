"""Where the application thinks it is and what it refuses to do; and, when a
display is there, the windows themselves.

Run:  python -m pytest tests
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import qemu_gui                                    # noqa: E402
from qemugui import command, model, paths          # noqa: E402


class InstallDir(unittest.TestCase):
    """One function answers "which folder am I installed in", for all three
    ways this program is ever started."""

    def test_running_from_source(self):
        got = paths.resolve_install_dir(frozen=False,
                                        executable="/usr/local/bin/python3.13",
                                        source_root="/Users/someone/Qemu-GUI-m68k")
        self.assertEqual(got, Path("/Users/someone/Qemu-GUI-m68k"))

    def test_frozen_inside_a_macos_application_bundle(self):
        """PyInstaller puts the executable four levels down, inside the
        bundle. The folder a person sees is the one holding the .app."""
        got = paths.resolve_install_dir(
            frozen=True,
            executable="/Applications/qemu-m68k/Qemu-system-m68k GUI.app/Contents/MacOS/Qemu-system-m68k GUI",
            source_root="/nowhere")
        self.assertEqual(got, Path("/Applications/qemu-m68k"))

    def test_frozen_bundle_nested_deeper(self):
        got = paths.resolve_install_dir(
            frozen=True,
            executable="/path/to/qemu/Qemu-system-m68k GUI.app/Contents/MacOS/sub/Qemu-system-m68k GUI",
            source_root="/nowhere")
        self.assertEqual(got, Path("/path/to/qemu"))

    def test_frozen_windows_executable(self):
        got = paths.resolve_install_dir(frozen=True,
                                        executable="/c/qemu-m68k/Qemu-system-m68k GUI.exe",
                                        source_root="/nowhere")
        self.assertEqual(got, Path("/c/qemu-m68k"))

    def test_source_root_points_at_the_entry_script(self):
        self.assertTrue((paths.SOURCE_ROOT / "qemu_gui.py").is_file())

    def test_everything_hangs_off_install_dir(self):
        with tempfile.TemporaryDirectory() as td:
            paths.use_install_dir(td)
            try:
                here = Path(td).resolve()
                self.assertEqual(paths.install_dir(), here)
                self.assertEqual(paths.machines_dir(), here / "Machines")
                self.assertEqual(paths.settings_path(), here / "Machines" / "settings.json")
                self.assertEqual(paths.qemu_binary("darwin"), here / "qemu-system-m68k")
                self.assertEqual(paths.qemu_binary("win32"), here / "qemu-system-m68k.exe")
                self.assertEqual(model.Library().root, here / "Machines")
            finally:
                paths.use_install_dir(None)

    def test_no_settings_are_stored_inside_a_bundle(self):
        """An application bundle is read-only; Machines is beside it."""
        paths.use_install_dir("/Applications/qemu-m68k")
        try:
            for p in (paths.machines_dir(), paths.settings_path()):
                self.assertNotIn(".app", str(p))
                self.assertTrue(str(p).startswith("/Applications/qemu-m68k/Machines"))
        finally:
            paths.use_install_dir(None)


class FrozenBundle(unittest.TestCase):
    """The packaged case, simulated on disk: a real .app-shaped folder with a
    real emulator file beside it, and the program started as if frozen.
    Proves install_dir() is wired to resolve_install_dir(), that the emulator
    is found from inside the bundle, and that Machines lands outside it."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.install = Path(self.td.name).resolve()
        exe = self.install / "Qemu-system-m68k GUI.app" / "Contents" / "MacOS" / "Qemu-system-m68k GUI"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        binary = self.install / paths.qemu_binary_name()
        binary.write_text("#!/bin/sh\n")
        os.chmod(binary, 0o755)
        self.exe = exe
        self._frozen = getattr(sys, "frozen", None)
        self._executable = sys.executable
        sys.frozen = True
        sys.executable = str(exe)

    def tearDown(self):
        sys.executable = self._executable
        if self._frozen is None:
            del sys.frozen
        else:
            sys.frozen = self._frozen
        self.td.cleanup()

    def test_a_frozen_bundle_finds_the_emulator_beside_the_bundle(self):
        self.assertEqual(paths.install_dir(), self.install)
        self.assertEqual(paths.machines_dir(), self.install / "Machines")
        self.assertNotIn(".app", str(paths.machines_dir()))
        self.assertIsNone(paths.startup_problem())
        self.assertTrue((self.install / "Machines").is_dir())
        # nothing was written inside the bundle
        self.assertEqual(sorted(p.name for p in (self.install / "Qemu-system-m68k GUI.app").rglob("*")),
                         ["Contents", "MacOS", "Qemu-system-m68k GUI"])

    def test_a_frozen_bundle_without_the_emulator_still_refuses(self):
        (self.install / paths.qemu_binary_name()).unlink()
        problem = paths.startup_problem()
        self.assertIsNotNone(problem)
        # the message is one short line and names no folder, so assert the thing
        # that actually matters here: the folder it resolved is the one holding
        # the bundle, not somewhere inside it.
        self.assertEqual(paths.install_dir(), self.install)
        self.assertNotIn(".app", str(paths.install_dir()))


class FakeMainWindow:
    """Stands in for the real window so the test can prove it is never built."""

    built = 0

    def __init__(self, *a, **k):
        FakeMainWindow.built += 1

    def mainloop(self):
        pass


class RefusesToStartWithoutTheEmulator(unittest.TestCase):
    """The emulator sitting beside the program is checked first, before
    anything else happens at all: no window, no machine list, no settings."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name).resolve()
        paths.use_install_dir(self.dir)
        FakeMainWindow.built = 0
        fake = types.ModuleType("qemugui.ui_main")
        fake.MainWindow = FakeMainWindow
        self._saved = sys.modules.get("qemugui.ui_main")
        sys.modules["qemugui.ui_main"] = fake

    def tearDown(self):
        paths.use_install_dir(None)
        if self._saved is None:
            sys.modules.pop("qemugui.ui_main", None)
        else:
            sys.modules["qemugui.ui_main"] = self._saved
        self.td.cleanup()

    def make_binary(self):
        p = self.dir / paths.qemu_binary_name()
        p.write_text("#!/bin/sh\n")
        os.chmod(p, 0o755)
        return p

    def test_missing_binary_stops_the_program(self):
        said = []
        rc = qemu_gui.main([], report_problem=said.append)
        self.assertEqual(rc, qemu_gui.EXIT_CANNOT_RUN)
        self.assertEqual(len(said), 1)
        message = said[0]
        self.assertIn(paths.qemu_binary_name(), message)
        self.assertNotIn("Traceback", message)
        # the user asked for one short line, not an explanation (2026-09-05)
        self.assertEqual(len(message.strip().splitlines()), 1)
        self.assertLess(len(message.strip()), 100)

    def test_missing_binary_builds_no_window_and_touches_nothing(self):
        rc = qemu_gui.main([], report_problem=lambda _m: None)
        self.assertEqual(rc, qemu_gui.EXIT_CANNOT_RUN)
        self.assertEqual(FakeMainWindow.built, 0)      # no degraded, complaining interface
        self.assertFalse((self.dir / "Machines").exists())   # nothing was created either
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [])

    def test_the_binary_is_checked_before_the_machines_folder(self):
        """Order matters: an unwritable install must still complain about the
        emulator first, because that is the thing that defines the folder."""
        os.chmod(self.dir, 0o500)
        try:
            self.assertIn(paths.qemu_binary_name(), paths.startup_problem())
        finally:
            os.chmod(self.dir, 0o700)

    def test_positive_control_the_check_passes_when_the_binary_is_there(self):
        """Proof the instrument works: the same call succeeds once the file
        is put beside the program, and then the window is built."""
        self.make_binary()
        self.assertIsNone(paths.startup_problem())
        rc = qemu_gui.main([], report_problem=lambda m: self.fail(m))
        self.assertEqual(rc, 0)
        self.assertEqual(FakeMainWindow.built, 1)
        self.assertTrue((self.dir / "Machines").is_dir())

    def test_unwritable_install_folder_is_explained(self):
        self.make_binary()
        os.chmod(self.dir, 0o500)
        try:
            problem = paths.startup_problem()
        finally:
            os.chmod(self.dir, 0o700)
        self.assertIsNotNone(problem)
        self.assertIn("Machines", problem)

    def test_nothing_offers_to_choose_a_folder(self):
        source = "\n".join((ROOT / "qemu_gui.py").read_text().splitlines()
                           + [(ROOT / "qemugui" / f).read_text()
                              for f in ("paths.py", "model.py", "command.py")])
        self.assertNotIn("askdirectory", source)
        for gone in ("library_dir", "qemu_dir_var", "discover_qemu_dir", "QEMU_DIR_CANDIDATES",
                     "BROWSE_FALLBACKS", "default_library_dir"):
            self.assertNotIn(gone, source, gone)




def _tk_available() -> bool:
    try:
        import tkinter as tk
        r = tk.Tk()
        r.destroy()
        return True
    except Exception:       # no tkinter, or no display
        return False


TK = _tk_available()


class _FakeRun:
    exit_code = None
    share = None

    def poll(self):
        return None

    def uptime(self):
        return 0.0


@unittest.skipUnless(TK, "no display")
class Windows(unittest.TestCase):
    """The main window and the editor, built for real and driven by hand."""

    def setUp(self):
        from qemugui import ui_main, ui_machine
        self.ui = ui_main
        self.ed = ui_machine
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name).resolve()
        paths.use_install_dir(self.dir)
        (self.dir / "Quadra800.rom").write_bytes(b"\0")
        (self.dir / "Quadra700.rom").write_bytes(b"\0")
        self.saved = (paths.HOST_PLATFORM, ui_main.start_in_terminal, ui_main.start_machine)
        self.calls: list[str] = []
        ui_main.start_in_terminal = lambda m, d: (self.calls.append("terminal"),
                                                  (Path(d) / "run.command", None))[1]
        ui_main.start_machine = lambda m, d: (self.calls.append("direct"), _FakeRun())[1]
        self.w = ui_main.MainWindow(paths.Settings(), settings_path=self.dir / "settings.json")
        self.w.withdraw()

    def tearDown(self):
        paths.HOST_PLATFORM, self.ui.start_in_terminal, self.ui.start_machine = self.saved
        self.w.destroy()
        paths.use_install_dir(None)
        self.td.cleanup()

    def add(self, name: str, mid: str) -> model.Machine:
        m = model.new_machine(name, mid)
        self.w.library.save(m)
        self.w.refresh_list(select=name)
        return m

    def test_the_command_line_is_shown(self):
        self.add("Q7", "q700")
        text = self.w.command_line.get("1.0", "end")
        self.assertIn("-M q700,audiodev=snd", text)
        self.assertIn("-icount shift=6", text)
        self.assertIn(str(self.dir / "Quadra700.rom"), text)

    def test_copy_command(self):
        m = self.add("Q8", "q800")
        self.w.copy_command()
        copied = self.w.clipboard_get()
        self.assertIn("qemu-system-m68k -M q800,audiodev=snd", copied)
        self.assertIn(m.network.mac, copied)

    def test_start_runs_from_here_and_stop_is_offered(self):
        self.add("Q8", "q800")
        self.assertIsNotNone(self.w.start_selected())
        self.assertEqual(self.calls, ["direct"])
        self.assertIn("Q8", self.w.running)
        self.assertTrue(self.w.run_status.cget("text").startswith("Running"))
        self.assertFalse(self.w.stop_button.instate(["disabled"]))

    def test_vmnet_goes_to_terminal(self):
        paths.HOST_PLATFORM = "darwin"
        m = self.add("V", "q800")
        m.network.mode = "vmnet-shared"
        self.w.library.save(m)
        self.assertIsNone(self.w.start_selected())
        self.assertEqual(self.calls, ["terminal"])

    def test_reset_pram_zeroes_the_file(self):
        m = self.add("P", "q800")
        pram = self.w.library.folder("P") / "pram.img"
        pram.write_bytes(b"\x07" * 512)
        from unittest import mock
        with mock.patch.object(self.ui, "confirm_reset_pram", return_value=True):
            self.w.reset_pram()
        self.assertEqual(pram.read_bytes(), b"\0" * 512)

    def editor(self, m: model.Machine, is_new: bool = False):
        saved = []
        e = self.ed.MachineEditor(self.w, m, self.w.library, str(self.dir),
                                  lambda mm, old: saved.append((mm, old)), is_new=is_new)
        e.withdraw()
        return e, saved

    def test_the_editor_round_trips_a_machine(self):
        m = model.new_machine("Round", "q800")
        m.scsi = [model.ScsiDrive(0, "disk", "/a.img"), model.ScsiDrive(3, "cdrom", "/b.iso")]
        m.floppies = [model.Floppy("/f.img", True), None]
        m.swap_opt_cmd = True
        m.easc = False
        m.screen = "1152x870x8"
        e, _ = self.editor(m)
        got = e.collect()
        e.destroy()
        self.assertEqual(got.to_dict(), m.to_dict())

    def test_switching_model_in_the_editor(self):
        e, _ = self.editor(model.new_machine("", "q800"), is_new=True)
        e.type_var.set("Macintosh Quadra 700")
        e._type_chosen()
        got = e.collect()
        self.assertEqual((got.machine, got.rom, got.ram_mb, got.screen, got.icount),
                         ("q700", "Quadra700.rom", 64, "1152x870x1", True))
        self.assertEqual(list(e.screen_cb.cget("values")),
                         [s.label for s in model.machine_type("q700").screens])
        self.assertTrue(e.easc_cb.instate(["disabled"]))
        e.destroy()

    def test_choosing_empty_removes_the_drive(self):
        m = model.new_machine("E", "q800")
        m.scsi = [model.ScsiDrive(2, "disk", "/a.img")]
        e, _ = self.editor(m)
        row = e.scsi_rows[2]
        row.kind.set("Empty")
        row._kind_changed()
        self.assertEqual(e.collect().scsi, [])
        e.destroy()

    def test_a_cd_file_is_recognised(self):
        e, _ = self.editor(model.new_machine("C", "q800"))
        e.scsi_rows[3].file.set("/cds/7.5.3.iso")
        self.assertEqual(e.collect().scsi, [model.ScsiDrive(3, "cdrom", "/cds/7.5.3.iso")])
        e.destroy()


if __name__ == "__main__":
    unittest.main()
