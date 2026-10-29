"""Golden-output tests for qemugui.command (headless, no Tk).

Run:  python -m pytest tests      or   python -m unittest discover -s tests
"""

from __future__ import annotations

import shlex
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from qemugui import command, model, systems  # noqa: E402
from qemugui.model import Machine, ScsiDrive, Floppy, HostFwd, Network  # noqa: E402

FIXTURES = HERE / "fixtures"
QD = "/Applications/Qemu-system-m68k"

# The user's launchers, verbatim from /Applications/Qemu-system-m68k.
USER_Q800 = r"""
./qemu-system-m68k \
-M q800 \
-drive file=pram.img,format=raw,if=mtd \
-m 128 \
-display sdl \
-bios Quadra800.rom \
-rtc base=localtime \
-device scsi-hd,scsi-id=4,drive=disk4 \
-drive file="/Users/hsp/mac-disks/system8.0.img",media=disk,format=raw,if=none,id=disk4 \
-nic user,model=dp83932,mac=08:00:07:12:34:56 \
"""

USER_Q700 = r"""
./qemu-system-m68k \
-M q700 \
-icount shift=6 \
-drive file=pram-q700.img,format=raw,if=mtd \
-m 64 \
-display sdl \
-bios Quadra700.rom \
-rtc base=localtime \
-device scsi-hd,scsi-id=0,drive=disk0 \
-drive file="/Volumes/Macdata/qemu/hd/aux/system7.1-q700.img",media=disk,format=raw,if=none,id=disk0 \
-nic user,model=dp83932,mac=08:00:07:12:34:57 \
"""


def user_tokens(text: str) -> list[str]:
    """A hand-written launcher as tokens, binary dropped, the ROM and PRAM
    names resolved against the install folder (the script cd's there)."""
    toks = shlex.split(text.replace("\\\n", " "))
    assert toks[0] == "./qemu-system-m68k"
    out = []
    for i, t in enumerate(toks[1:], 1):
        if toks[i - 1] == "-bios":
            t = f"{QD}/{t}"
        if t.startswith("file=pram"):
            t = f"file={QD}/{t[len('file='):]}"
        out.append(t)
    return out


def load_fixture(name: str) -> Machine:
    return Machine.load(FIXTURES / name)


def argv_for(m: Machine, platform: str = "darwin", machine_dir: str = "/M/x") -> list[str]:
    return command.build_argv(m, QD, machine_dir, platform)


def option(argv: list[str], name: str) -> list[str]:
    """Every value given to option *name*."""
    return [argv[i + 1] for i, t in enumerate(argv[:-1]) if t == name]


class UserLaunchers(unittest.TestCase):
    """The primary correctness test: the two launchers the user runs today.
    What the GUI adds on top is spelled out: the sound backend, wired to the
    machine's sound chip, and the screen."""

    def check(self, fixture: str, text: str, model_id: str, screen: str):
        got = argv_for(load_fixture(fixture))[1:]
        want = user_tokens(text)
        want[want.index(model_id)] = f"{model_id},audiodev=snd"
        if "shift=6" in want:                    # the GUI keeps the clock in real time
            want[want.index("shift=6")] = "shift=6,align=on"
        want += ["-g", screen, "-audiodev", "coreaudio,id=snd"]
        # both floppy drives exist, empty, and the control connection
        want += ["-drive", "if=floppy,index=0", "-drive", "if=floppy,index=1",
                 "-qmp", f"tcp:127.0.0.1:{command.qmp_port(load_fixture(fixture))},"
                         "server=on,wait=off"]
        self.assertEqual(sorted(got), sorted(want))

    def test_q800(self):
        self.check("q800.json", USER_Q800, "q800", "640x480")    # 800x600 always gave 640x480

    def test_q700(self):
        self.check("q700.json", USER_Q700, "q700", "1152x870")   # the old depth is dropped

    def test_binary_is_absolute_and_first(self):
        self.assertEqual(argv_for(load_fixture("q800.json"))[0], f"{QD}/qemu-system-m68k")

    def test_shell_rendering_shape(self):
        text = command.launcher_text(load_fixture("q700.json"), QD, "/M/x", "darwin")
        lines = text.splitlines()
        self.assertEqual(lines[0], "#!/bin/bash")
        self.assertIn('cd "$(dirname "$0")"', lines)
        body = [ln for ln in lines if ln.startswith("-") or ln.startswith("/")]
        for ln in body[:-1]:
            self.assertTrue(ln.endswith(" \\"), ln)
        self.assertFalse(body[-1].endswith("\\"))
        self.assertIn("-M q700,audiodev=snd \\", lines)
        self.assertIn("-icount shift=6,align=on \\", lines)
        self.assertIn("-device scsi-hd,scsi-id=0,drive=disk0 \\", lines)

    def test_one_line_round_trips(self):
        argv = argv_for(load_fixture("q800.json"), machine_dir="/M/Quadra 800")
        line = command.one_line(argv, "/M/Quadra 800")
        toks = shlex.split(line)
        self.assertEqual(toks[:3], ["cd", "/M/Quadra 800", "&&"])
        self.assertEqual(toks[3:], argv)


class Machines(unittest.TestCase):
    """What a fresh machine of each model starts as."""

    def test_new_q800(self):
        m = model.new_machine("A", "q800")
        argv = argv_for(m, machine_dir="/M/A")
        self.assertEqual(option(argv, "-M"), ["q800,audiodev=snd"])
        self.assertEqual(option(argv, "-m"), ["128"])
        self.assertEqual(option(argv, "-bios"), [])          # no ROM until one is picked
        self.assertEqual(option(argv, "-g"), ["832x624"])
        self.assertNotIn("-icount", argv)
        self.assertIn("file=/M/A/pram.img,format=raw,if=mtd", argv)
        self.assertEqual(option(argv, "-rtc"), ["base=localtime"])
        self.assertTrue(option(argv, "-nic")[0].startswith("user,model=dp83932,mac=08:00:07:"))

    def test_new_q700(self):
        m = model.new_machine("B", "q700")
        argv = argv_for(m, machine_dir="/M/B")
        self.assertEqual(option(argv, "-M"), ["q700,audiodev=snd"])
        self.assertNotIn("-icount", argv)
        self.assertEqual(option(argv, "-m"), ["64"])
        self.assertEqual(option(argv, "-bios"), [])
        self.assertEqual(option(argv, "-g"), ["832x624"])

    def test_icount_is_a_choice_on_either(self):
        m = model.new_machine("B", "q700")
        m.icount = False
        self.assertNotIn("-icount", argv_for(m))
        m = model.new_machine("A", "q800")
        m.icount = True
        self.assertEqual(option(argv_for(m), "-icount"), [systems.ICOUNT_OPTION])

    def test_mouse_speed_only_when_not_the_default(self):
        m = model.new_machine("A", "q800")
        self.assertNotIn("-global", argv_for(m))
        m.mouse_speed = 35
        self.assertEqual(option(argv_for(m), "-global"), ["adb-mouse.speed=35"])

    def test_mouse_speed_round_trips_and_bad_values_fall_back(self):
        m = model.new_machine("A", "lc475")
        m.mouse_speed = 75
        self.assertEqual(Machine.from_dict(m.to_dict()).mouse_speed, 75)
        for bad in (None, "fast", 0, 999):
            d = m.to_dict()
            d["mouse_speed"] = bad
            self.assertEqual(Machine.from_dict(d).mouse_speed, systems.DEFAULT_MOUSE_SPEED)

    def test_easc_off_only_on_the_quadra_800(self):
        m = model.new_machine("A", "q800")
        m.easc = False
        self.assertEqual(option(argv_for(m), "-M"), ["q800,audiodev=snd,easc=off"])
        m = model.new_machine("B", "q700")
        m.easc = False                     # no such property there: ignored
        self.assertEqual(option(argv_for(m), "-M"), ["q700,audiodev=snd"])

    def test_every_screen_in_the_table_is_a_valid_g(self):
        for mid, screens in systems.SCREENS.items():
            for s in screens:
                m = model.new_machine("A", mid)
                m.screen = s.id
                self.assertEqual(option(argv_for(m), "-g"), [f"{s.width}x{s.height}"])
                self.assertEqual(model.validate(m, None, check_files=False)[0], [])


class Drives(unittest.TestCase):

    def test_scsi_disk_and_cd(self):
        m = model.new_machine("A", "q800")
        m.scsi = [ScsiDrive(3, "cdrom", "/iso/7.5.3.iso"), ScsiDrive(0, "disk", "/hd/8.1.img")]
        argv = argv_for(m)
        devs = option(argv, "-device")
        self.assertEqual(devs, ["scsi-hd,scsi-id=0,drive=disk0", "scsi-cd,scsi-id=3,drive=cd3"])
        drives = option(argv, "-drive")
        self.assertIn("file=/hd/8.1.img,media=disk,format=raw,if=none,id=disk0", drives)
        self.assertIn("file=/iso/7.5.3.iso,media=cdrom,format=raw,readonly=on,if=none,id=cd3",
                      drives)

    def test_the_quadra_900s_external_bus(self):
        """The same ID on both buses; the external one names its bus."""
        m = model.new_machine("A", "q900")
        m.scsi = [ScsiDrive(3, "cdrom", "/iso/8.1.iso", bus=1), ScsiDrive(0, "disk", "/hd/a.img"),
                  ScsiDrive(0, "disk", "/hd/b.img", bus=1)]
        self.assertEqual(model.validate(m, None, check_files=False)[0], [])
        argv = argv_for(m)
        self.assertEqual(option(argv, "-device"), [
            "scsi-hd,scsi-id=0,drive=disk0",
            "scsi-hd,bus=scsi.0,scsi-id=0,drive=xdisk0",
            "scsi-cd,bus=scsi.0,scsi-id=3,drive=xcd3"])
        drives = option(argv, "-drive")
        self.assertIn("file=/hd/b.img,media=disk,format=raw,if=none,id=xdisk0", drives)
        self.assertIn("file=/iso/8.1.iso,media=cdrom,format=raw,readonly=on,if=none,id=xcd3",
                      drives)

    def test_no_external_bus_on_one_bus_models(self):
        m = model.new_machine("A", "q700")
        m.scsi = [ScsiDrive(3, "cdrom", "/iso/8.1.iso", bus=1)]
        self.assertTrue(model.validate(m, None, check_files=False)[0])
        self.assertEqual(option(argv_for(m), "-device"), [])

    def test_two_drives_on_one_id_of_one_bus(self):
        m = model.new_machine("A", "q900")
        m.scsi = [ScsiDrive(3, "cdrom", "/a.iso", bus=1), ScsiDrive(3, "disk", "/b.img", bus=1)]
        self.assertTrue(model.validate(m, None, check_files=False)[0])

    def test_relative_image_resolves_in_the_machine_folder(self):
        m = model.new_machine("A", "q800")
        m.scsi = [ScsiDrive(1, "disk", "hd.img")]
        self.assertIn("file=/M/A/hd.img,media=disk,format=raw,if=none,id=disk1",
                      option(argv_for(m, machine_dir="/M/A"), "-drive"))

    def test_a_comma_in_a_path_is_doubled(self):
        m = model.new_machine("A", "q800")
        m.scsi = [ScsiDrive(0, "disk", "/hd/a,b.img")]
        self.assertIn("file=/hd/a,,b.img,media=disk,format=raw,if=none,id=disk0",
                      option(argv_for(m), "-drive"))

    def test_qcow2_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.img"
            p.write_bytes(b"QFI\xfb" + b"\0" * 100)
            m = model.new_machine("A", "q800")
            m.scsi = [ScsiDrive(0, "disk", str(p), "raw")]
            self.assertIn(f"file={p},media=disk,format=qcow2,if=none,id=disk0",
                          option(argv_for(m), "-drive"))

    def test_floppies(self):
        m = model.new_machine("A", "q800")
        m.floppies = [Floppy("/fd/Disk Tools.img", readonly=True), Floppy("/fd/b.img")]
        drives = option(argv_for(m), "-drive")
        self.assertIn("file=/fd/Disk Tools.img,if=floppy,index=0,format=raw,snapshot=on", drives)
        self.assertIn("file=/fd/b.img,if=floppy,index=1,format=raw", drives)

    def test_empty_floppy_drives_exist(self):
        m = model.new_machine("A", "q800")
        self.assertEqual([d for d in option(argv_for(m), "-drive") if "if=floppy" in d],
                         ["if=floppy,index=0", "if=floppy,index=1"])

    def test_control_connection(self):
        m = model.new_machine("A", "q800")
        port = command.qmp_port(m)
        self.assertTrue(command.QMP_PORT_BASE <= port
                        < command.QMP_PORT_BASE + command.QMP_PORT_COUNT)
        self.assertEqual(option(argv_for(m), "-qmp"),
                         [f"tcp:127.0.0.1:{port},server=on,wait=off"])
        self.assertEqual(option(command.build_argv(m, QD, "/M/x", "darwin", 45999), "-qmp"),
                         ["tcp:127.0.0.1:45999,server=on,wait=off"])
        self.assertEqual(command.qmp_port(m), command.qmp_port(model.new_machine("A", "q700")))

    def test_second_floppy_alone_keeps_its_index(self):
        m = model.new_machine("A", "q800")
        m.floppies = [None, Floppy("/fd/b.img")]
        self.assertIn("file=/fd/b.img,if=floppy,index=1,format=raw", option(argv_for(m), "-drive"))

    def test_no_pram(self):
        m = model.new_machine("A", "q800")
        m.pram = ""
        self.assertFalse([d for d in option(argv_for(m), "-drive") if "if=mtd" in d])

    def test_pram_elsewhere(self):
        m = model.new_machine("A", "q800")
        m.pram = "/Applications/Qemu-system-m68k/pram.img"
        self.assertIn("file=/Applications/Qemu-system-m68k/pram.img,format=raw,if=mtd",
                      option(argv_for(m), "-drive"))


class DisplayAndSound(unittest.TestCase):

    def test_cocoa_swap(self):
        m = model.new_machine("A", "q800")
        m.display = "cocoa"
        self.assertEqual(option(argv_for(m), "-display"), ["cocoa"])
        m.swap_opt_cmd = True
        self.assertEqual(option(argv_for(m), "-display"), ["cocoa,swap-opt-cmd=on"])
        m.display = "sdl"
        self.assertEqual(option(argv_for(m), "-display"), ["sdl"])

    def test_audio_backends(self):
        m = model.new_machine("A", "q800")
        self.assertEqual(option(argv_for(m, "darwin"), "-audiodev"), ["coreaudio,id=snd"])
        self.assertEqual(option(argv_for(m, "linux"), "-audiodev"), ["sdl,id=snd"])
        m.audio = "none"
        self.assertEqual(option(argv_for(m), "-audiodev"), ["none,id=snd"])


class Network_(unittest.TestCase):

    def nic(self, **kw) -> str:
        m = model.new_machine("A", "q800")
        m.network = Network(mac="08:00:07:01:02:03", **kw)
        return option(argv_for(m), "-nic")[0]

    def test_modes(self):
        self.assertEqual(self.nic(mode="user"), "user,model=dp83932,mac=08:00:07:01:02:03")
        self.assertEqual(self.nic(mode="none"), "none")
        self.assertEqual(self.nic(mode="vmnet-shared"),
                         "vmnet-shared,model=dp83932,mac=08:00:07:01:02:03")
        self.assertEqual(self.nic(mode="vmnet-bridged", ifname="en0"),
                         "vmnet-bridged,ifname=en0,model=dp83932,mac=08:00:07:01:02:03")

    def test_port_forwarding(self):
        self.assertEqual(self.nic(mode="user", hostfwd=[HostFwd("tcp", "8080", "80"), HostFwd()]),
                         "user,model=dp83932,mac=08:00:07:01:02:03,hostfwd=tcp::8080-:80")

    def lc475(self, pds="", **kw) -> list[str]:
        m = model.new_machine("A", "lc475")
        m.pds = pds
        m.network = Network(mac="08:00:07:01:02:03", **kw)
        return argv_for(m)

    def test_lc475_without_card_has_no_ethernet(self):
        argv = self.lc475(mode="user")
        self.assertEqual(option(argv, "-nic"), ["none"])
        self.assertEqual(option(argv, "-netdev"), [])

    def test_lc475_ethernet_card(self):
        argv = self.lc475("ethernet", mode="user", hostfwd=[HostFwd("tcp", "8080", "80")])
        self.assertEqual(option(argv, "-nic"), ["none"])
        self.assertEqual(option(argv, "-netdev"), ["user,hostfwd=tcp::8080-:80,id=net0"])
        self.assertIn("mac-pds-ethernet,netdev=net0,mac=08:00:07:01:02:03",
                      option(argv, "-device"))

    def test_lc475_ethernet_card_bridged(self):
        argv = self.lc475("ethernet", mode="vmnet-bridged", ifname="en0")
        self.assertEqual(option(argv, "-netdev"), ["vmnet-bridged,ifname=en0,id=net0"])

    def test_lc475_ethernet_card_unplugged(self):
        argv = self.lc475("ethernet", mode="none")
        self.assertEqual(option(argv, "-netdev"), [])
        self.assertIn("mac-pds-ethernet,mac=08:00:07:01:02:03", option(argv, "-device"))

    def test_the_lcs_take_the_ethernet_card(self):
        for mid in ("maclc", "maclc2", "maclc3"):
            m = model.new_machine("A", mid)
            m.pds = "ethernet"
            m.network = Network(mac="08:00:07:01:02:03", mode="user")
            self.assertIn("mac-pds-ethernet,netdev=net0,mac=08:00:07:01:02:03",
                          option(argv_for(m), "-device"), mid)

    def test_card_ignored_on_a_model_without_the_slot(self):
        m = model.new_machine("A", "q800")
        m.pds = "ethernet"
        m.network = Network(mode="user", mac="08:00:07:01:02:03")
        argv = argv_for(m)
        self.assertEqual(option(argv, "-nic"), ["user,model=dp83932,mac=08:00:07:01:02:03"])
        self.assertNotIn("mac-pds-ethernet", " ".join(argv))

    def test_nubus_ethernet_card(self):
        for mid in ("macii", "maciix", "maciicx", "maciifx"):
            m = model.new_machine("A", mid)
            m.pds = "nubus-ethernet"
            m.network = Network(mode="user", mac="08:00:07:01:02:03")
            argv = argv_for(m)
            self.assertEqual(option(argv, "-nic"), ["none"])
            self.assertEqual(option(argv, "-netdev"), ["user,id=net0"])
            self.assertIn("nubus-ethernet,netdev=net0,mac=08:00:07:01:02:03",
                          option(argv, "-device"))

    def test_nubus_card_not_in_the_pds_slot(self):
        m = model.new_machine("A", "lc475")
        m.pds = "nubus-ethernet"
        self.assertNotIn("nubus-ethernet", " ".join(argv_for(m)))

    def test_vmnet_runs_under_sudo(self):
        m = model.new_machine("A", "q800")
        m.network.mode = "vmnet-shared"
        self.assertTrue(command.needs_sudo(m, "darwin"))
        text = command.launcher_text(m, QD, "/M/A", "darwin")
        self.assertIn("sudo -v", text)
        self.assertIn(f"sudo {QD}/qemu-system-m68k \\", text)

    def test_low_port_needs_sudo_high_does_not(self):
        m = model.new_machine("A", "q800")
        m.network.hostfwd = [HostFwd("tcp", "80", "80")]
        self.assertTrue(command.needs_sudo(m, "darwin"))
        m.network.hostfwd = [HostFwd("tcp", "8080", "80")]
        self.assertFalse(command.needs_sudo(m, "darwin"))
        self.assertNotIn("sudo", command.launcher_text(m, QD, "/M/A", "darwin"))

    def test_mac_is_apple_and_stable(self):
        m = model.new_machine("A", "q800")
        self.assertRegex(m.network.mac, r"^08:00:07(:[0-9a-f]{2}){3}$")
        self.assertEqual(Machine.from_json(m.to_json()).network.mac, m.network.mac)
        self.assertEqual(argv_for(m), argv_for(Machine.from_json(m.to_json())))


class ExtraArgsAndWindows(unittest.TestCase):

    def test_extra_args_last(self):
        m = model.new_machine("A", "q800")
        m.extra_args = '-serial stdio -name "My Mac"'
        self.assertEqual(argv_for(m)[-4:], ["-serial", "stdio", "-name", "My Mac"])

    def test_bat(self):
        m = model.new_machine("Mac OS 8", "q800")
        m.rom = "Quadra800.rom"
        m.scsi = [ScsiDrive(0, "disk", r"C:\disks\8.1.img")]
        argv = command.build_argv(m, r"C:\qemu-m68k", r"C:\Machines\Mac OS 8", "win32")
        self.assertEqual(argv[0], r"C:\qemu-m68k\qemu-system-m68k.exe")
        text = command.render_bat(argv, m.name)
        self.assertIn('cd /d "%~dp0"', text)
        self.assertIn("title Mac OS 8", text)
        self.assertIn(r"-bios C:\qemu-m68k\Quadra800.rom", text)
        self.assertIn('-audiodev "dsound,id=snd"', text)
        self.assertIn(r'-drive "file=C:\disks\8.1.img,media=disk,format=raw,if=none,id=disk0"',
                      text)
        body = [ln for ln in text.split("\r\n") if ln.startswith("-")]
        self.assertFalse(body[-1].endswith("^"))


class HostDisk(unittest.TestCase):
    def host(self, mid="q700", **kw):
        m = model.new_machine("A", mid)
        m.share = model.Share("/Users/me/Mac Share", ftp=False, volume=True, **kw)
        return m

    def test_card_device_and_folder(self):
        argv = argv_for(self.host())
        self.assertIn(f"nubus-virtio-mmio,romfile={QD}/declrom", option(argv, "-device"))
        self.assertIn("virtio-9p-device,fsdev=hostshare,mount_tag=Host", option(argv, "-device"))
        self.assertEqual(option(argv, "-fsdev"),
                         ["local,id=hostshare,path=/Users/me/Mac Share,"
                          "security_model=none,macos_compat=on"])

    def test_disk_name(self):
        argv = argv_for(self.host(volume_name="Shared, too"))
        self.assertIn("virtio-9p-device,fsdev=hostshare,mount_tag=Shared,, too",
                      option(argv, "-device"))

    def test_mac_ii_family_with_ethernet_card(self):
        m = self.host("maciicx")
        m.pds = "nubus-ethernet"
        self.assertTrue(option(argv_for(m), "-fsdev"))

    def test_lc475_ethernet_card_carries_it(self):
        m = self.host("lc475")
        m.pds = "ethernet"
        argv = argv_for(m)
        devices = option(argv, "-device")
        self.assertTrue(option(argv, "-fsdev"))
        self.assertFalse([d for d in devices if d.startswith("nubus-virtio-mmio")])
        self.assertFalse([d for d in devices if d.startswith("mac-pds-ethernet,")])
        card = [d for d in devices if d.startswith("mac-pds-ethernet-virtio,")]
        self.assertEqual(len(card), 1)
        self.assertIn("declrom-pds", card[0])
        # the virtio devices exist only once the card is there
        self.assertLess(devices.index(card[0]),
                        [i for i, d in enumerate(devices) if d.startswith("virtio-9p")][0])

    def test_lc475_ethernet_card_without_the_disk(self):
        m = self.host("lc475")
        m.pds = "ethernet"
        m.share.volume = False
        devices = option(argv_for(m), "-device")
        self.assertTrue([d for d in devices if d.startswith("mac-pds-ethernet,")])
        self.assertFalse([d for d in devices if "virtio" in d])

    def test_lc475_alone(self):
        devices = option(argv_for(self.host("lc475")), "-device")
        self.assertTrue([d for d in devices if d.startswith("nubus-virtio-mmio,")])

    def test_off(self):
        m = self.host()
        m.share.volume = False
        self.assertEqual(option(argv_for(m), "-fsdev"), [])
        self.assertFalse([d for d in option(argv_for(m), "-device") if "virtio" in d])


if __name__ == "__main__":
    unittest.main()
