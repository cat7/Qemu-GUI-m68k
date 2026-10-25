"""The machine record: dataclasses, JSON load/save, checks, machine folders.

No Tk in here. ``machine.json`` schema version 1.

Three rules this file exists to enforce:

* Machines live in the ``Machines`` folder next to the program. There is no
  configurable location and no per-machine emulator override.
* **Nothing here ever deletes a disk image.** Deleting a machine removes the
  handful of files the program itself wrote (see ``OWNED_FILES``) and leaves
  every other file, disk images above all, exactly where it is.
* **Nothing here chooses a disk.** Hard disks, CDs and floppies start empty
  and stay empty until the person picks something. The only files a new
  machine names are its model's ROM (by plain name, next to the emulator)
  and its own PRAM file inside its own folder.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from . import paths, systems
from .systems import (MACHINES, MAC_PREFIX, RAM_MIN, machine_type, normalise_machine_id,
                      screen_by_id)

SCHEMA = 1
NAME_RE = re.compile(r"^[A-Za-z0-9._ -]+$")
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

# ---------------------------------------------------------------- naming

SCSI_IDS = list(range(7))          # 7 is the Mac itself
SCSI_SELF_ID = 7
SCSI_SELF_LABEL = "Macintosh"


def scsi_name(sid: int) -> str:
    return f"Device {sid}"


FLOPPY_DRIVES = 2


def floppy_name(i: int) -> str:
    return "Internal floppy" if i == 0 else "External floppy"


DRIVE_KINDS = ("disk", "cdrom")
FORMATS = ("raw", "qcow2")

FORMAT_MAGIC = ((b"QFI\xfb", "qcow2"),)
MAGIC_LENGTH = max(len(magic) for magic, _ in FORMAT_MAGIC)


def detect_format(path: str) -> str:
    """The format of an image file by its magic number: "qcow2" or "raw".
    Anything unknown, missing or unreadable answers "raw". Never raises."""
    try:
        with open(str(path or ""), "rb") as fh:
            head = fh.read(MAGIC_LENGTH)
    except OSError:
        return "qcow2" if str(path).lower().endswith((".qcow2", ".qcow")) else "raw"
    for magic, fmt in FORMAT_MAGIC:
        if head.startswith(magic):
            return fmt
    return "raw"


DISPLAYS = {"darwin": ("cocoa", "sdl"), "win32": ("sdl", "gtk"), "linux": ("sdl", "gtk")}


def default_display(platform: str = paths.HOST_PLATFORM) -> str:
    """The first choice offered on this computer, which is what a new machine
    starts with: ``cocoa`` on a Mac, ``sdl`` anywhere else."""
    return DISPLAYS.get("win32" if paths.is_windows(platform) else platform, ("sdl",))[0]


def displays_for_host(platform: str = paths.HOST_PLATFORM) -> tuple[str, ...]:
    return DISPLAYS.get("win32" if paths.is_windows(platform) else platform, ("sdl", "gtk"))


AUDIO_MODES = ("default", "sdl", "none")
NETWORK_MODES = ("user", "none", "vmnet-bridged", "vmnet-shared", "vmnet-host", "tap")
# platform each mode is meant for (None = all); "darwin" | "win32"
NETWORK_MODE_PLATFORM = {"user": None, "none": None, "vmnet-bridged": "darwin",
                         "vmnet-shared": "darwin", "vmnet-host": "darwin", "tap": "win32"}
NETWORK_MODES_WITH_IFNAME = ("vmnet-bridged", "tap")

# The PRAM file a new machine keeps in its own folder. QEMU needs it to exist;
# the program makes it, 512 zero bytes, the first time the machine is saved.
PRAM_NAME = "pram.img"
PRAM_SIZE = 512

# A 1.44 MB floppy image. 400K and 800K (GCR) disks are not emulated yet.
FLOPPY_SIZE = 1474560
GCR_SIZES = {409600: "400K", 819200: "800K"}

# The complete list of files Qemu-system-m68k GUI is allowed to delete from a
# machine folder. Anything not on this list -- above all a disk image -- is
# left alone, whatever it is called. It is an allow-list, not a deny-list, so
# a new kind of file is safe by default.
OWNED_FILES = ("machine.json", "run.command", "run.bat", "last-run.log",
               PRAM_NAME, ".DS_Store")

# Only used to word messages ("your disk images are still there"); nothing is
# deleted or kept on the strength of an extension.
IMAGE_SUFFIXES = {".img", ".dsk", ".qcow2", ".iso", ".toast", ".cdr", ".hfv", ".hfs",
                  ".raw", ".image"}


def looks_like_disk_image(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_SUFFIXES


def random_mac(rng: random.Random | None = None) -> str:
    """A fresh card address with Apple's prefix. A new machine gets one and
    keeps it, so the Mac's network settings stay put between runs."""
    r = rng or random.SystemRandom()
    return MAC_PREFIX + "".join(f":{r.randrange(256):02x}" for _ in range(3))


@dataclass
class ScsiDrive:
    id: int = 0
    kind: str = "disk"           # disk | cdrom
    file: str = ""
    format: str = "raw"

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "file": self.file, "format": self.format}

    @classmethod
    def from_dict(cls, d: Any) -> "ScsiDrive | None":
        if not isinstance(d, dict):
            return None
        return cls(int(d.get("id", 0)), str(d.get("kind", "disk")), str(d.get("file", "")),
                   str(d.get("format", "raw")))


@dataclass
class Floppy:
    file: str = ""
    readonly: bool = False       # changes are thrown away when the machine stops

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Any) -> "Floppy | None":
        if not isinstance(d, dict):
            return None
        return cls(str(d.get("file", "")), bool(d.get("readonly", False)))


HOSTFWD_PROTOS = ("tcp", "udp")
HOSTFWD_ROWS = 4


@dataclass
class HostFwd:
    proto: str = "tcp"
    host_port: str = ""
    guest_port: str = ""

    def to_dict(self) -> dict:
        return {"proto": self.proto, "host_port": self.host_port, "guest_port": self.guest_port}

    @classmethod
    def from_dict(cls, d: Any) -> "HostFwd":
        if not isinstance(d, dict):
            return cls()
        return cls(str(d.get("proto") or "tcp"), str(d.get("host_port") or "").strip(),
                   str(d.get("guest_port") or "").strip())

    @property
    def empty(self) -> bool:
        return not (self.host_port or self.guest_port)


def _port_ok(text: str) -> bool:
    return text.isascii() and text.isdigit() and 1 <= int(text) <= 65535


@dataclass
class Network:
    mode: str = "user"           # none | user | vmnet-bridged | vmnet-shared | vmnet-host | tap
    mac: str = ""
    ifname: str = ""             # host interface for vmnet-bridged (en0) / tap
    hostfwd: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"mode": self.mode, "mac": self.mac}
        if self.mode in NETWORK_MODES_WITH_IFNAME or self.ifname:
            d["ifname"] = self.ifname
        rules = [r.to_dict() for r in self.hostfwd if not r.empty]
        if rules:
            d["hostfwd"] = rules
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "Network":
        if not isinstance(d, dict):
            return cls(mac=random_mac())
        rules = d.get("hostfwd")
        return cls(str(d.get("mode", "user")), str(d.get("mac") or random_mac()),
                   str(d.get("ifname", "") or ""),
                   [HostFwd.from_dict(r) for r in rules] if isinstance(rules, list) else [])

    @property
    def needs_sudo(self) -> bool:
        """vmnet backends need root (or the com.apple.vm.networking entitlement)."""
        return self.mode.startswith("vmnet-")

    @property
    def low_host_port(self) -> bool:
        """Slirp with a non-empty forward whose host port is below 1024."""
        return self.mode == "user" and any(
            not r.empty and str(r.host_port).strip().isdigit() and 0 < int(r.host_port) < 1024
            for r in self.hostfwd)

    @property
    def platform(self) -> str | None:
        return NETWORK_MODE_PLATFORM.get(self.mode)


NETWORK_MODE_LABELS = {"user": "default (slirp)"}


def network_mode_label(mode: str) -> str:
    return NETWORK_MODE_LABELS.get(mode, mode)


def network_mode_by_label(label: str) -> str:
    for mode, shown in NETWORK_MODE_LABELS.items():
        if shown == label:
            return mode
    return label


def network_modes_for_host(platform: str = paths.HOST_PLATFORM, current: str | None = None) -> list[str]:
    """Modes the editor offers on *platform*, plus whatever the record holds."""
    host = "win32" if paths.is_windows(platform) else platform
    out = [m for m in NETWORK_MODES if NETWORK_MODE_PLATFORM[m] in (None, host)]
    if current and current not in out:
        out.append(current)
    return out


def network_labels_for_host(platform: str = paths.HOST_PLATFORM,
                            current: str | None = None) -> list[str]:
    return [network_mode_label(m) for m in network_modes_for_host(platform, current)]


def default_ifname(mode: str, platform: str = paths.HOST_PLATFORM) -> str:
    if mode == "vmnet-bridged" and platform == "darwin":
        return "en0"
    return ""


def ifname_label(platform: str = paths.HOST_PLATFORM) -> str:
    return "Vmnet host interface:" if platform == "darwin" else "Tap device name:"


AUDIO_BACKEND_LABELS = {"coreaudio": "CoreAudio", "dsound": "DirectSound", "sdl": "Default (sdl)"}


def default_audio_label(platform: str = paths.HOST_PLATFORM) -> str:
    """What the "default" sound choice is called on this host."""
    backend = paths.resolve_audio("default", platform)
    return AUDIO_BACKEND_LABELS.get(backend, backend)


SHARE_SCOPES = ("guest-only", "all-interfaces")
SHARE_DEFAULT_USER = "guest"


@dataclass
class Share:
    folder: str = ""             # "" = no shared folder
    user: str = SHARE_DEFAULT_USER
    password: str = ""
    scope: str = "guest-only"    # guest-only | all-interfaces
    ftp: bool = False            # serve the folder over FTP

    def to_dict(self) -> dict:
        return {"folder": self.folder, "user": self.user, "password": self.password,
                "scope": self.scope, "ftp": self.ftp}

    @classmethod
    def from_dict(cls, d: Any) -> "Share":
        if not isinstance(d, dict):
            return cls()
        return cls(str(d.get("folder", "") or ""),
                   str(d.get("user", SHARE_DEFAULT_USER) or SHARE_DEFAULT_USER),
                   str(d.get("password", "") or ""),
                   str(d.get("scope", "guest-only") or "guest-only"),
                   bool(d.get("ftp", False)))

    @property
    def enabled(self) -> bool:
        return bool(self.folder.strip())

    @property
    def ftp_on(self) -> bool:
        return self.enabled and self.ftp


@dataclass
class Machine:
    name: str = "New machine"
    machine: str = "q800"        # a key of systems.MACHINES, the -M value
    ram_mb: int = 128
    rom: str = ""                # relative = next to the emulator
    pram: str = PRAM_NAME        # relative = in the machine's folder; "" = not kept
    screen: str = "800x600x8"    # a systems.Screen id, -g
    display: str = "cocoa"
    swap_opt_cmd: bool = False   # cocoa only
    icount: bool = False         # -icount shift=ICOUNT_SHIFT
    audio: str = "default"
    easc: bool = True            # q800 only: Enhanced ASC (off = plain ASC)
    network: Network = field(default_factory=Network)
    scsi: list = field(default_factory=list)
    floppies: list = field(default_factory=lambda: [None] * FLOPPY_DRIVES)
    share: Share = field(default_factory=Share)
    extra_args: str = ""
    notes: str = ""

    @property
    def type(self):
        return machine_type(self.machine)

    # ---- JSON ----
    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "name": self.name,
            "machine": self.machine,
            "ram_mb": self.ram_mb,
            "rom": self.rom,
            "pram": self.pram,
            "screen": self.screen,
            "display": self.display,
            "swap_opt_cmd": self.swap_opt_cmd,
            "icount": self.icount,
            "audio": self.audio,
            "easc": self.easc,
            "network": self.network.to_dict(),
            "scsi": [d.to_dict() for d in sorted(self.scsi, key=lambda s: s.id)],
            "floppies": [f.to_dict() if f else None for f in self.floppies],
            "share": self.share.to_dict(),
            "extra_args": self.extra_args,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Machine":
        mid = normalise_machine_id(d.get("machine"))
        t = MACHINES[mid]
        floppies = [Floppy.from_dict(x) for x in list(d.get("floppies") or [])][:FLOPPY_DRIVES]
        while len(floppies) < FLOPPY_DRIVES:
            floppies.append(None)
        scsi = [s for s in (ScsiDrive.from_dict(x) for x in d.get("scsi") or []) if s]
        return cls(
            name=str(d.get("name", "New machine")),
            machine=mid,
            ram_mb=int(d.get("ram_mb", t.ram_mb)),
            rom=str(d.get("rom", t.rom) or ""),
            pram=str(d.get("pram", PRAM_NAME) or ""),
            screen=str(d.get("screen") or t.screen),
            display=str(d.get("display") or default_display()),
            swap_opt_cmd=bool(d.get("swap_opt_cmd", False)),
            icount=bool(d.get("icount", t.icount)),
            audio=str(d.get("audio", "default")),
            easc=bool(d.get("easc", True)),
            network=Network.from_dict(d.get("network")),
            scsi=scsi,
            floppies=floppies,
            share=Share.from_dict(d.get("share")),
            extra_args=str(d.get("extra_args", "")),
            notes=str(d.get("notes", "")),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "Machine":
        return cls.from_dict(json.loads(text))

    @classmethod
    def load(cls, path: Path) -> "Machine":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    def copy(self) -> "Machine":
        return Machine.from_dict(self.to_dict())

    # ---- helpers ----
    def scsi_by_id(self, sid: int) -> ScsiDrive | None:
        for s in self.scsi:
            if s.id == sid:
                return s
        return None

    def first_free_scsi(self, prefer: int = 0) -> int | None:
        order = [prefer] + [i for i in SCSI_IDS if i != prefer]
        for sid in order:
            if self.scsi_by_id(sid) is None:
                return sid
        return None

    def image_paths(self) -> list[str]:
        """Every image this record points at, in no particular order."""
        return [f for _label, f in _image_files(self) if f]


def new_machine(name: str, machine_id: str) -> Machine:
    """Seed a record from one of the models: memory, ROM name, screen, speed
    limit, a fresh card address. No disk, CD or floppy is filled in."""
    t = machine_type(machine_id)
    return Machine(name=name, machine=t.id, ram_mb=t.ram_mb, rom=t.rom, pram=PRAM_NAME,
                   screen=t.screen, display=default_display(), icount=t.icount,
                   network=Network(mac=random_mac()))


def apply_machine_type(m: Machine, machine_id: str) -> None:
    """Switch a record to another model, carrying over what still fits: the
    ROM follows if it was the old model's default, memory is capped, the
    screen falls back to the new model's default if the old one is not
    offered, and the speed limit takes the new model's default."""
    old, new = m.type, machine_type(machine_id)
    if old.id == new.id:
        return
    m.machine = new.id
    if not m.rom or m.rom == old.rom:
        m.rom = new.rom
    if m.ram_mb > new.ram_max or m.ram_mb == old.ram_mb:
        m.ram_mb = new.ram_mb
    if screen_by_id(new.id, m.screen) is None:
        m.screen = new.screen
    m.icount = new.icount


def pram_path(m: Machine, machine_dir: str | Path) -> Path | None:
    """The PRAM file on this host, or None when it is not kept."""
    if not m.pram.strip():
        return None
    return Path(paths.join_path(str(machine_dir), str(Path(m.pram.strip()).expanduser()),
                                paths.HOST_PLATFORM))


def write_blank_pram(path: Path | str) -> Path:
    """A fresh PRAM: 512 zero bytes. Refuses to write over an existing file;
    use Library.reset_pram for the machine's own one."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "xb") as fh:
        fh.write(b"\0" * PRAM_SIZE)
    return p


def floppy_problem(path: str) -> str | None:
    """Why a floppy image will not work, or None. Only the size is known."""
    try:
        size = Path(path).expanduser().stat().st_size
    except OSError:
        return None
    if size == FLOPPY_SIZE:
        return None
    if size in GCR_SIZES:
        return f"{Path(path).name} is a {GCR_SIZES[size]} disk; only 1.44 MB works yet."
    if size - 84 in (FLOPPY_SIZE, *GCR_SIZES):
        return f"{Path(path).name} looks like a Disk Copy 4.2 image; convert it to raw first."
    return f"{Path(path).name} is not a 1.44 MB floppy image."


def start_blockers(m: Machine, qemu_dir: str | None = None) -> list[str]:
    """Reasons this machine cannot be started yet, in plain words.

    Separate from :func:`validate` on purpose: a half-finished machine can be
    saved and come back to another day, but it cannot be run."""
    out = []
    if not (m.rom or "").strip():
        out.append("No ROM chosen.")
    elif qemu_dir and not Path(paths.join_path(qemu_dir, m.rom, paths.HOST_PLATFORM)).is_file():
        out.append(f"The ROM is missing: {paths.join_path(qemu_dir, m.rom, paths.HOST_PLATFORM)}")
    return out


# ---------------------------------------------------------------- checking

def validate(m: Machine, qemu_dir: str | None, platform: str = paths.HOST_PLATFORM,
             check_files: bool = True, machine_dir: str | None = None) -> tuple[list[str], list[str]]:
    """Return (things that must be fixed, things worth knowing). Saving is
    blocked by the first list, allowed with the second."""
    errors: list[str] = []
    warnings: list[str] = []
    t = m.type

    if not m.name or not m.name.strip():
        errors.append("This machine has no name.")
    elif not NAME_RE.match(m.name) or m.name.strip() != m.name:
        errors.append("That name will not work.")
    if m.machine not in MACHINES:
        errors.append(f"'{m.machine}' is not a machine this program knows.")
    if not (RAM_MIN <= m.ram_mb <= t.ram_max):
        errors.append(f"Memory has to be between {RAM_MIN} and {t.ram_max} MB on the {t.label}.")
    if screen_by_id(t.id, m.screen) is None:
        errors.append(f"The {t.label} cannot show {m.screen}.")
    if m.display == "cocoa" and platform != "darwin":
        warnings.append("'cocoa' only works on a Mac.")
    if m.audio not in AUDIO_MODES:
        errors.append(f"'{m.audio}' is not a sound setting.")
    net = m.network
    if net.mode not in NETWORK_MODES:
        errors.append(f"'{net.mode}' is not a network setting.")
    else:
        if net.mode != "none" and not MAC_RE.match(net.mac):
            errors.append("The card address has to look like 08:00:07:12:34:56.")
        if net.mode in NETWORK_MODES_WITH_IFNAME and not net.ifname.strip():
            errors.append("No interface named.")
        for r in net.hostfwd:
            if r.empty:
                continue
            if r.proto not in HOSTFWD_PROTOS:
                errors.append(f"'{r.proto}' is not a forwarding protocol.")
            if not (_port_ok(r.host_port) and _port_ok(r.guest_port)):
                errors.append("Port forwarding needs host and guest ports from 1 to 65535.")
        host = "win32" if paths.is_windows(platform) else platform
        if net.platform is not None and net.platform != host:
            warnings.append("This network setting only works on "
                            f"{'a Mac' if net.platform == 'darwin' else 'Windows'}.")
    share = m.share
    if share.scope not in SHARE_SCOPES:
        errors.append(f"'{share.scope}' is not a sharing setting.")
    if share.enabled and not Path(share.folder.strip()).expanduser().is_dir():
        errors.append("The shared folder is not a folder that exists.")
    if share.ftp_on:
        if not share.user.strip():
            errors.append("The shared folder has no user name.")
        if share.scope == "all-interfaces" and not share.password:
            errors.append("Sharing on all interfaces needs a password.")
        if share.scope == "guest-only" and net.mode != "user":
            warnings.append("Guest only sharing is only reachable with default (slirp).")

    seen_ids = set()
    for s in m.scsi:
        if s.id in seen_ids:
            errors.append(f"Two SCSI drives are both set to device {s.id}.")
        seen_ids.add(s.id)
        if s.id == SCSI_SELF_ID:
            errors.append(f"SCSI device {SCSI_SELF_ID} is the Macintosh.")
        elif s.id not in SCSI_IDS:
            errors.append(f"SCSI device {s.id} does not exist.")
        if s.kind not in DRIVE_KINDS:
            errors.append(f"SCSI device {s.id} has no drive type.")
    if len(m.floppies) != FLOPPY_DRIVES:
        errors.append(f"There are not {FLOPPY_DRIVES} floppy drives.")

    if check_files:
        qd = qemu_dir or ""
        if qd and paths.has_qemu(qd, platform) and m.rom:
            rom = paths.join_path(qd, m.rom, platform)
            if not Path(rom).is_file():
                warnings.append(f"The Mac's ROM is missing: {rom}")
        for label, f in _image_files(m):
            if not f:
                continue
            p = Path(f).expanduser()
            if not p.is_absolute():
                if machine_dir is None:
                    continue
                p = Path(machine_dir) / p
            if not p.is_file():
                warnings.append(f"{label}: {f} is not there.")
        floppy_ok = systems.machine_type(m.machine).floppy
        for i, fd in enumerate(m.floppies):
            if fd and fd.file:
                if not floppy_ok:
                    warnings.append(f"{floppy_name(i)}: the "
                                    f"{systems.machine_type(m.machine).label} has no "
                                    "working floppy drive yet; the disk is left out.")
                    continue
                why = floppy_problem(paths.join_path(machine_dir or "", fd.file, platform))
                if why:
                    warnings.append(why)
        if m.pram.strip() and machine_dir is not None:
            p = pram_path(m, machine_dir)
            if p and not p.is_file() and Path(m.pram).is_absolute():
                warnings.append(f"The PRAM file {p} is not there yet.")
    return errors, warnings


def _image_files(m: Machine):
    for s in m.scsi:
        yield f"SCSI {scsi_name(s.id)}", s.file
    for i, fd in enumerate(m.floppies):
        if fd:
            yield floppy_name(i), fd.file


# ---------------------------------------------------------------- machines

@dataclass
class DeleteResult:
    """What ``Library.delete`` actually did."""

    folder: Path
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    folder_removed: bool = False

    @property
    def kept_images(self) -> list[str]:
        return [f for f in self.kept if looks_like_disk_image(f)]


class Library:
    """The Machines folder: one subfolder per machine, named after it."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root).expanduser() if root else paths.machines_dir()

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, name: str) -> Path:
        return self.root / name

    def json_path(self, name: str) -> Path:
        return self.folder(name) / "machine.json"

    def names(self) -> list[str]:
        if not self.root.is_dir():
            return []
        out = []
        for p in sorted(self.root.iterdir(), key=lambda x: x.name.lower()):
            if p.is_dir() and (p / "machine.json").is_file():
                out.append(p.name)
        return out

    def load(self, name: str) -> Machine:
        path = self.json_path(name)
        m = Machine.load(path)
        m.name = name  # the folder is authoritative
        if '"mac"' not in path.read_text(encoding="utf-8"):
            m.save(path)     # keep the card address it was just given
        return m

    def load_all(self) -> list[Machine]:
        out = []
        for n in self.names():
            try:
                out.append(self.load(n))
            except (OSError, ValueError, KeyError, TypeError):
                out.append(Machine(name=n, notes="(unreadable)"))
        return out

    def save(self, m: Machine, old_name: str | None = None) -> Path:
        """Write machine.json; rename the folder if the name changed; make the
        machine's own blank PRAM file if it does not have one yet.

        Renaming moves the folder, so any image kept inside it moves with it:
        the record is re-pointed at the new location rather than left aiming
        at a path that no longer exists. Nothing is deleted or overwritten.
        """
        if not NAME_RE.match(m.name):
            raise ValueError("illegal machine name")
        self.ensure()
        if old_name and old_name != m.name and self.folder(old_name).is_dir():
            if self.folder(m.name).exists():
                raise FileExistsError(f"A machine called '{m.name}' already exists.")
            old_folder, new_folder = self.folder(old_name), self.folder(m.name)
            moved = [(old_folder, new_folder),
                     (old_folder.resolve(), new_folder.parent.resolve() / new_folder.name)]
            old_folder.rename(new_folder)
            _repoint_images(m, moved)
        folder = self.folder(m.name)
        folder.mkdir(parents=True, exist_ok=True)
        m.save(self.json_path(m.name))
        own = self.own_pram(m)
        if own and not own.exists():
            write_blank_pram(own)
        return folder

    def own_pram(self, m: Machine) -> Path | None:
        """The PRAM file when it is the machine's own (pram.img directly in
        its folder), which the program may create and reset; else None."""
        p = pram_path(m, self.folder(m.name))
        if p and p.parent.resolve() == self.folder(m.name).resolve() and p.name == PRAM_NAME:
            return p
        return None

    def exists(self, name: str) -> bool:
        """A folder of that name is there, whatever is in it."""
        return self.folder(name).exists()

    def has_record(self, name: str) -> bool:
        """A machine of that name is really there. A bare folder is not one:
        creating a disk image before saving makes the folder first, and that
        must not read as "you already have a machine called this"."""
        return self.json_path(name).is_file()

    def duplicate(self, name: str, new_name: str) -> Machine:
        """Copy the record into a new folder, with a blank PRAM and a card
        address of its own (two machines with one address confuse a network).
        Disk images are not copied and not touched: the copy starts out
        pointing at the same image files."""
        if self.exists(new_name):
            raise FileExistsError(f"A machine called '{new_name}' already exists.")
        m = self.load(name)
        m.name = new_name
        m.network.mac = random_mac()
        self.save(m)
        return m

    def folder_contents(self, name: str) -> list[str]:
        d = self.folder(name)
        if not d.is_dir():
            return []
        return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() or p.is_symlink())

    def delete_preview(self, name: str) -> tuple[list[str], list[str]]:
        """(files Delete would remove, files Delete would leave behind) --
        so the person can be told before anything happens."""
        contents = self.folder_contents(name)
        removed = [f for f in contents if f in OWNED_FILES]
        kept = [f for f in contents if f not in OWNED_FILES]
        return removed, kept

    def delete(self, name: str) -> DeleteResult:
        """Remove this machine's record, launcher, log and PRAM.

        Only the names in ``OWNED_FILES`` are ever deleted, and only directly
        inside the machine's own folder. A disk image -- whatever it is
        called, wherever it sits -- is never deleted, and the folder itself
        stays if anything is left in it.
        """
        d = self.folder(name)
        result = DeleteResult(folder=d)
        if not d.is_dir() or d.resolve().parent != self.root.resolve():
            return result
        for f in OWNED_FILES:
            p = d / f
            if p.is_symlink() or p.is_file():
                try:
                    p.unlink()
                except OSError:
                    continue
                result.removed.append(f)
        result.kept = self.folder_contents(name)
        if not result.kept:
            # rmdir refuses on anything that is not empty, so this cannot
            # take a file with it.
            for sub in sorted((p for p in d.rglob("*") if p.is_dir()),
                              key=lambda p: len(p.parts), reverse=True):
                try:
                    sub.rmdir()
                except OSError:
                    pass
            try:
                d.rmdir()
                result.folder_removed = True
            except OSError:
                pass
        return result

    def reset_pram(self, m: Machine) -> Path | None:
        """Zero the machine's own PRAM (the emulated equivalent of pulling
        the battery). Only ever the pram.img in its own folder, never a
        file chosen elsewhere; returns it, or None if there is none."""
        p = self.own_pram(m)
        if p is None or p.is_symlink():
            return None
        p.write_bytes(b"\0" * PRAM_SIZE)
        return p


IMAGE_NAME_SUFFIXES = (".img", ".qcow2", ".dsk", ".hfv")


def check_new_image_path(folder: Path | str, name: str, fmt: str) -> tuple[Path | None, str | None]:
    """Where a new disk image would be created, or a plain reason it cannot be.

    Refusing to write over anything that already exists is the point of this
    function: a disk image can be a whole afternoon of installing an old
    system, and Qemu-system-m68k GUI never overwrites one.
    """
    name = (name or "").strip()
    if not name:
        return None, "Give the disk a name."
    if "/" in name or "\\" in name or name in (".", ".."):
        return None, "The name cannot contain slashes."
    if not name.lower().endswith(IMAGE_NAME_SUFFIXES):
        name += ".qcow2" if fmt == "qcow2" else ".img"
    target = Path(folder) / name
    if target.exists() or target.is_symlink():
        return None, f"There is already a file called {name}."
    return target, None


def _repoint_images(m: Machine, moved: list[tuple[Path, Path]]) -> None:
    """After a folder rename, point image paths at the folder's new place, so
    an image kept inside the machine's folder is never left orphaned."""
    def fixed(p: str) -> str:
        if not p:
            return p
        for old_folder, new_folder in moved:
            try:
                rel = Path(p).relative_to(old_folder)
            except ValueError:
                continue
            return str(new_folder / rel)
        return p

    for s in m.scsi:
        s.file = fixed(s.file)
    for fd in m.floppies:
        if fd:
            fd.file = fixed(fd.file)
    m.pram = fixed(m.pram)
