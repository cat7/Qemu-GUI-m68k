"""The machine record, the model table, the checks, and the one promise that
matters: no code path deletes or overwrites a disk image.

Headless: nothing here imports Tk.
"""

from __future__ import annotations

import ast
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from qemugui import command, model, systems  # noqa: E402
from qemugui.model import Machine, ScsiDrive, Floppy, Share, HostFwd  # noqa: E402


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class TheModelTable(unittest.TestCase):

    def test_all_models_are_offered(self):
        self.assertEqual(systems.machine_ids(), ["q800", "q700", "q900", "lc475"])
        self.assertEqual(systems.machine_labels(),
                         ["Macintosh Quadra 800", "Macintosh Quadra 700",
                          "Macintosh Quadra 900", "Macintosh LC 475"])

    def test_every_model_is_consistent(self):
        for t in systems.MACHINES.values():
            self.assertIn(t.ram_mb, t.ram_choices, t.id)
            self.assertLessEqual(max(t.ram_choices), t.ram_max, t.id)
            self.assertIsNotNone(systems.screen_by_id(t.id, t.screen), t.id)
            ids = [s.id for s in t.screens]
            self.assertEqual(len(ids), len(set(ids)), t.id)
            labels = [s.label for s in t.screens]
            self.assertEqual(len(labels), len(set(labels)), t.id)

    def test_memory_limits(self):
        self.assertEqual(systems.MACHINES["q800"].ram_max, 1024)
        self.assertEqual(systems.MACHINES["q700"].ram_max, 256)

    def test_q700_needs_icount_q800_does_not(self):
        self.assertTrue(systems.MACHINES["q700"].icount)
        self.assertFalse(systems.MACHINES["q800"].icount)

    def test_screen_labels(self):
        s = systems.Screen(832, 624, 8, 'Apple 16" Color')
        self.assertEqual(s.id, "832x624x8")
        self.assertEqual(s.label, 'Apple 16" Color — 832 × 624, 256 colours')

    def test_the_q700_monitors(self):
        sizes = sorted({(s.width, s.height) for s in systems.SCREENS["q700"]})
        self.assertEqual(sizes, [(512, 384), (640, 480), (640, 870), (832, 624), (1152, 870)])
        self.assertEqual(len(systems.SCREENS["q700"]), 23)
        self.assertIsNone(systems.screen_by_id("q700", "800x600x8"))
        self.assertIsNone(systems.screen_by_id("q700", "640x870x24"))   # greyscale
        self.assertIsNone(systems.screen_by_id("q700", "1152x870x24"))
        self.assertTrue(all(s.monitor for s in systems.SCREENS["q700"]))
        self.assertEqual(systems.Screen(800, 600, 24).label, "800 × 600, millions")


class Record(unittest.TestCase):

    def test_every_part_survives_a_round_trip(self):
        m = model.new_machine("Everything", "q700")
        m.ram_mb = 32
        m.screen = "640x480x1"
        m.display = "sdl"
        m.swap_opt_cmd = True
        m.icount = False
        m.audio = "none"
        m.easc = False
        m.pram = "/somewhere/pram.img"
        m.scsi = [ScsiDrive(0, "disk", "/a.img", "qcow2"), ScsiDrive(3, "cdrom", "/b.iso")]
        m.floppies = [Floppy("/f.img", True), None]
        m.network.mode = "vmnet-bridged"
        m.network.ifname = "en1"
        m.network.hostfwd = [HostFwd("udp", "5000", "5001")]
        m.share = Share("/tmp", "u", "p", "all-interfaces", True)
        m.extra_args = "-serial stdio"
        m.notes = "notes"
        self.assertEqual(Machine.from_json(m.to_json()), m)

    def test_an_unknown_model_falls_back_to_the_default(self):
        self.assertEqual(Machine.from_dict({"machine": "q950"}).machine, systems.DEFAULT_MACHINE)

    def test_a_bare_record_takes_its_models_defaults(self):
        m = Machine.from_dict({"name": "x", "machine": "q700"})
        self.assertEqual((m.ram_mb, m.rom, m.screen, m.icount, m.pram),
                         (64, "Quadra700.rom", "832x624x8", True, "pram.img"))
        self.assertRegex(m.network.mac, r"^08:00:07:")
        self.assertEqual(m.floppies, [None, None])

    def test_new_machine_fills_no_disk(self):
        for mid in systems.machine_ids():
            m = model.new_machine("x", mid)
            self.assertEqual(m.scsi, [])
            self.assertEqual(m.floppies, [None, None])
            self.assertEqual(m.share.folder, "")

    def test_two_new_machines_get_different_addresses(self):
        macs = {model.new_machine("x", "q800").network.mac for _ in range(20)}
        self.assertGreater(len(macs), 1)


class SwitchingModel(unittest.TestCase):

    def test_defaults_follow(self):
        m = model.new_machine("x", "q800")
        model.apply_machine_type(m, "q700")
        self.assertEqual((m.machine, m.rom, m.ram_mb, m.screen, m.icount),
                         ("q700", "Quadra700.rom", 64, "832x624x8", True))
        model.apply_machine_type(m, "q800")
        self.assertEqual((m.machine, m.rom, m.ram_mb, m.icount), ("q800", "Quadra800.rom", 128, False))
        self.assertEqual(m.screen, "800x600x8")      # no 832x624 there: its default
        m.screen = "1152x870x8"
        model.apply_machine_type(m, "q700")
        self.assertEqual(m.screen, "1152x870x8")     # the q700 offers it too: kept

    def test_own_choices_are_kept_where_they_fit(self):
        m = model.new_machine("x", "q800")
        m.rom = "/my/roms/Q800-patched.rom"
        m.ram_mb = 32
        model.apply_machine_type(m, "q700")
        self.assertEqual(m.rom, "/my/roms/Q800-patched.rom")
        self.assertEqual(m.ram_mb, 32)

    def test_memory_is_capped(self):
        m = model.new_machine("x", "q800")
        m.ram_mb = 512
        model.apply_machine_type(m, "q700")
        self.assertLessEqual(m.ram_mb, 256)


class Checks(unittest.TestCase):

    def errors(self, m: Machine) -> list[str]:
        return model.validate(m, None, check_files=False)[0]

    def test_a_new_machine_is_fine(self):
        for mid in systems.machine_ids():
            self.assertEqual(self.errors(model.new_machine("x", mid)), [])

    def test_memory_over_the_models_limit(self):
        m = model.new_machine("x", "q700")
        m.ram_mb = 512
        self.assertTrue(any("256" in e for e in self.errors(m)))
        m = model.new_machine("x", "q800")
        m.ram_mb = 512
        self.assertEqual(self.errors(m), [])

    def test_a_screen_the_model_cannot_show(self):
        m = model.new_machine("x", "q700")
        m.screen = "800x600x8"
        self.assertTrue(self.errors(m))

    def test_scsi_7_is_the_mac(self):
        m = model.new_machine("x", "q800")
        m.scsi = [ScsiDrive(7, "disk", "/a.img")]
        self.assertTrue(any("Macintosh" in e for e in self.errors(m)))

    def test_two_drives_on_one_id(self):
        m = model.new_machine("x", "q800")
        m.scsi = [ScsiDrive(0, "disk", "/a.img"), ScsiDrive(0, "cdrom", "/b.iso")]
        self.assertTrue(self.errors(m))

    def test_mac_address(self):
        m = model.new_machine("x", "q800")
        m.network.mac = "nonsense"
        self.assertTrue(self.errors(m))
        m.network.mode = "none"
        self.assertEqual(self.errors(m), [])

    def test_floppy_sizes(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for name, size in (("ok.img", 1474560), ("gcr.img", 819200),
                               ("dc42.image", 819200 + 84), ("odd.img", 1000)):
                (d / name).write_bytes(b"\0" * size)
            self.assertIsNone(model.floppy_problem(str(d / "ok.img")))
            self.assertIn("800K", model.floppy_problem(str(d / "gcr.img")))
            self.assertIn("Disk Copy", model.floppy_problem(str(d / "dc42.image")))
            self.assertIn("1.44", model.floppy_problem(str(d / "odd.img")))
            m = model.new_machine("x", "q800")
            m.floppies[0] = Floppy(str(d / "gcr.img"))
            _e, warnings = model.validate(m, None, machine_dir=td)
            self.assertTrue(any("800K" in w for w in warnings))

    def test_start_needs_the_rom(self):
        with tempfile.TemporaryDirectory() as td:
            m = model.new_machine("x", "q800")
            self.assertTrue(model.start_blockers(m, td))           # not there
            (Path(td) / "Quadra800.rom").write_bytes(b"\0")
            self.assertEqual(model.start_blockers(m, td), [])
            m.rom = ""
            self.assertEqual(model.start_blockers(m, td), ["No ROM chosen."])


class Pram(unittest.TestCase):

    def test_saving_makes_a_blank_pram_once(self):
        with tempfile.TemporaryDirectory() as td:
            lib = model.Library(Path(td))
            m = model.new_machine("Q", "q800")
            folder = lib.save(m)
            p = folder / "pram.img"
            self.assertEqual(p.read_bytes(), b"\0" * 512)
            p.write_bytes(b"\x01" * 512)            # the Mac wrote its settings
            lib.save(m)
            self.assertEqual(p.read_bytes(), b"\x01" * 512)

    def test_reset_zeroes_only_the_machines_own(self):
        with tempfile.TemporaryDirectory() as td:
            lib = model.Library(Path(td) / "Machines")
            m = model.new_machine("Q", "q800")
            folder = lib.save(m)
            (folder / "pram.img").write_bytes(b"\x01" * 512)
            self.assertEqual(lib.reset_pram(m), folder / "pram.img")
            self.assertEqual((folder / "pram.img").read_bytes(), b"\0" * 512)
            elsewhere = Path(td) / "pram.img"
            elsewhere.write_bytes(b"\x02" * 512)
            m.pram = str(elsewhere)
            lib.save(m)
            self.assertIsNone(lib.reset_pram(m))
            self.assertEqual(elsewhere.read_bytes(), b"\x02" * 512)

    def test_a_blank_pram_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "pram.img"
            p.write_bytes(b"\x05" * 512)
            with self.assertRaises(FileExistsError):
                model.write_blank_pram(p)
            self.assertEqual(p.read_bytes(), b"\x05" * 512)

    def test_no_pram_makes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            lib = model.Library(Path(td))
            m = model.new_machine("Q", "q800")
            m.pram = ""
            folder = lib.save(m)
            self.assertFalse((folder / "pram.img").exists())


class DeleteNeverTouchesADiskImage(unittest.TestCase):
    """A disk image can be hours of installing an operating system. Deleting
    a machine removes the record, the launcher, the log and the PRAM, and
    nothing else."""

    def machine_with_images(self, root: Path):
        lib = model.Library(root)
        m = model.new_machine("System 7", "q800")
        lib.save(m)
        folder = lib.folder("System 7")
        command.write_launcher(m, "/q", str(folder), "darwin")
        (folder / "last-run.log").write_text("log\n")
        images = {}
        for name, body in (("System 7.img", b"a whole afternoon of installing" * 100),
                           ("scratch.qcow2", b"qcow2 stand-in" * 50),
                           ("Install CD.iso", b"an iso" * 10),
                           ("notes about this disk.txt", b"my own notes")):
            (folder / name).write_bytes(body)
            images[name] = hashlib.sha256(body).hexdigest()
        return lib, folder, images

    def test_delete_leaves_disk_images_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            lib, folder, images = self.machine_with_images(Path(td))
            will_go, will_stay = lib.delete_preview("System 7")
            self.assertEqual(sorted(will_go),
                             ["last-run.log", "machine.json", "pram.img", "run.command"])
            self.assertEqual(sorted(will_stay), sorted(images))
            result = lib.delete("System 7")
            self.assertEqual(sorted(result.removed), sorted(will_go))
            self.assertFalse(result.folder_removed)
            for name, want in images.items():
                self.assertEqual(digest(folder / name), want, name)
            self.assertEqual(sorted(result.kept_images),
                             ["Install CD.iso", "System 7.img", "scratch.qcow2"])
            self.assertEqual(lib.names(), [])

    def test_folder_goes_away_only_when_nothing_is_left_in_it(self):
        with tempfile.TemporaryDirectory() as td:
            lib = model.Library(Path(td))
            lib.save(model.new_machine("Empty", "q700"))
            result = lib.delete("Empty")
            self.assertTrue(result.folder_removed)
            self.assertFalse(lib.folder("Empty").exists())

    def test_delete_refuses_to_walk_out_of_the_machines_folder(self):
        with tempfile.TemporaryDirectory() as td:
            outside = Path(td) / "outside"
            outside.mkdir()
            (outside / "machine.json").write_text("{}")
            lib = model.Library(Path(td) / "Machines")
            lib.ensure()
            self.assertEqual(lib.delete("../outside").removed, [])
            self.assertTrue((outside / "machine.json").is_file())

    def test_a_full_lifecycle_never_changes_an_image(self):
        """Create, save, rename, duplicate, reset the PRAM, write the
        launcher, delete -- and the images come out byte-identical."""
        with tempfile.TemporaryDirectory() as td:
            lib, folder, images = self.machine_with_images(Path(td))
            m = lib.load("System 7")
            m.scsi = [ScsiDrive(0, "disk", str(folder / "System 7.img"))]
            lib.save(m)
            m.name = "System 7.5"
            lib.save(m, old_name="System 7")
            new_folder = lib.folder("System 7.5")
            self.assertEqual(lib.load("System 7.5").scsi[0].file,
                             str(new_folder / "System 7.img"))
            copy = lib.duplicate("System 7.5", "System 7.5 copy")
            self.assertNotEqual(copy.network.mac, m.network.mac)
            lib.reset_pram(lib.load("System 7.5"))
            command.write_launcher(m, "/q", str(new_folder), "darwin")
            lib.delete("System 7.5 copy")
            lib.delete("System 7.5")
            for name, want in images.items():
                self.assertEqual(digest(new_folder / name), want, name)

    def test_creating_a_disk_never_overwrites_one(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            (folder / "System 7.img").write_bytes(b"precious")
            target, why = model.check_new_image_path(folder, "System 7", "raw")
            self.assertIsNone(target)
            self.assertIn("System 7.img", why)
            target, why = model.check_new_image_path(folder, "System 7", "qcow2")
            self.assertEqual(target, folder / "System 7.qcow2")
            self.assertIsNone(model.check_new_image_path(folder, "a/b", "raw")[0])


class NoOtherPathCanRemoveAFile(unittest.TestCase):
    """A source-level guard, so a later change cannot quietly reintroduce a
    recursive delete. Every call that can remove something is accounted for."""

    ALLOWED = {
        "rmtree": set(),
        "remove": set(),
        "rmdir": {"delete"},
        "unlink": {"delete", "startup_problem"},
    }

    def test_removal_calls_are_only_in_the_places_that_may_remove(self):
        offenders = []
        for src in sorted(ROOT.glob("qemugui/*.py")) + [ROOT / "qemu_gui.py"]:
            tree = ast.parse(src.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call):
                        name = getattr(inner.func, "attr", None) or getattr(inner.func, "id", None)
                        if name in self.ALLOWED and node.name not in self.ALLOWED[name]:
                            offenders.append(f"{src.name}:{inner.lineno} {name}() in {node.name}()")
        self.assertEqual(offenders, [])



class PdsSlot(unittest.TestCase):

    def test_round_trip(self):
        m = model.new_machine("A", "lc475")
        m.pds = "ethernet"
        self.assertEqual(Machine.from_json(m.to_json()).pds, "ethernet")
        self.assertEqual(Machine.from_dict({"machine": "lc475"}).pds, "")

    def test_switching_to_a_model_without_the_slot_empties_it(self):
        m = model.new_machine("A", "lc475")
        m.pds = "ethernet"
        model.apply_machine_type(m, "q800")
        self.assertEqual(m.pds, "")

    def test_validation(self):
        m = model.new_machine("A", "lc475")
        m.network.mode = "user"
        _e, warnings = model.validate(m, None, check_files=False)
        self.assertTrue(any("PDS slot" in w for w in warnings))
        m.pds = "ethernet"
        errors, warnings = model.validate(m, None, check_files=False)
        self.assertEqual(errors, [])
        self.assertFalse(any("PDS slot" in w for w in warnings))
        m2 = model.new_machine("B", "q800")
        m2.pds = "ethernet"
        errors, _w = model.validate(m2, None, check_files=False)
        self.assertTrue(any("no slot" in e for e in errors))

if __name__ == "__main__":
    unittest.main()
