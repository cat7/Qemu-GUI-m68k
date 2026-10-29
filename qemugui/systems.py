"""The Macintosh models the Machine list offers, and the screens each one can
drive.

Everything that differs between models lives in the two tables below, so a
new model is one more ``MachineType`` line plus its list of screens, and a
new screen mode is one more ``Screen`` line. Nothing in ``command.py``
branches on a model's id; it reads these fields.

Models name no files: the ROM, disks, CDs and floppies are always the
person's own choice.
"""

from __future__ import annotations

from dataclasses import dataclass

# -icount shift=N runs the CPU at a fixed speed (2^N ns per instruction):
# shift=6 is roughly a real 25 MHz 68040. align=on keeps the Mac's clock in
# step with real time; without it a fast host runs the clock several times
# too fast, and key repeat and double-click times shrink with it.
ICOUNT_SHIFT = 6
ICOUNT_OPTION = f"shift={ICOUNT_SHIFT},align=on"

# The emulated ADB mouse passes on this percentage of the host's motion
# (-global adb-mouse.speed=N). The host has already accelerated the motion
# and Mac OS accelerates it again, so the emulator's default is 50.
MOUSE_SPEEDS = (25, 35, 50, 75, 100, 150)
DEFAULT_MOUSE_SPEED = 50

RAM_MIN = 4

# Apple's own Ethernet prefix, which the Mac OS network drivers expect.
MAC_PREFIX = "08:00:07"

@dataclass(frozen=True)
class Screen:
    """One monitor, as -g WIDTHxHEIGHT.

    On the Quadra 700 and 900 the size picks the monitor (the emulated DAFB
    reports that monitor's sense code). Only the size is given: Mac OS starts
    in the depth its PRAM remembers (256 colours on a fresh one), and colour
    depth and resolution are changed in the Monitors control panel."""
    width: int
    height: int
    monitor: str = ""            # the Apple monitor this size is, shown first

    @property
    def id(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def label(self) -> str:
        text = f"{self.width} × {self.height}"
        return f"{self.monitor} — {text}" if self.monitor else text


# The Apple monitors the built-in video of every model here can drive, each
# at the size it starts in.
MONITORS: tuple[Screen, ...] = (
    Screen(512, 384, 'Apple 12" RGB'),
    Screen(640, 480, 'Apple 13" RGB / VGA'),
    Screen(640, 870, 'Apple 15" Portrait (greyscale)'),
    Screen(832, 624, 'Apple 16" Color'),
    Screen(1152, 870, 'Apple 21" Color'),
)
# The LC and LC II's V8 chip senses three monitors; the LC III's Sonora
# also the 16" and VGA ones.
LC_MONITORS: tuple[Screen, ...] = (
    Screen(512, 384, 'Apple 12" RGB'),
    Screen(640, 480, 'Apple 13" RGB'),
    Screen(640, 870, 'Apple 15" Portrait (greyscale)'),
)
LC3_MONITORS: tuple[Screen, ...] = (
    Screen(512, 384, 'Apple 12" RGB'),
    Screen(640, 480, 'Apple 13" RGB / VGA'),
    Screen(640, 870, 'Apple 15" Portrait (greyscale)'),
    Screen(832, 624, 'Apple 16" Color'),
)
# The Mac II family has no built-in video: QEMU fits its own NuBus
# video card in slot 9, which starts in any of these sizes.
SCREENS: dict[str, tuple[Screen, ...]] = {
    **{mid: MONITORS for mid in ("q800", "q700", "q900", "q950", "lc475", "macii",
                                 "maciix", "maciicx", "maciifx")},
    "maclc": LC_MONITORS,
    "maclc2": LC_MONITORS,
    "maclc3": LC3_MONITORS,
}

# Older records named sizes that are no monitor: the screen they really got
OLD_SCREENS = {"800x600": "640x480"}


@dataclass(frozen=True)
class MachineType:
    id: str                      # the -M value
    label: str
    ram_mb: int                  # what a new machine starts with
    ram_max: int                 # QEMU refuses more
    ram_choices: tuple[int, ...]
    screen: str                  # the Screen.id a new machine starts with
    icount: bool                 # "Run at real-machine speed" on by default
    easc: bool                   # has the "easc" machine property
    floppy: bool = True          # QEMU emulates its floppy drives
    onboard_nic: bool = True     # built-in SONIC Ethernet (-nic model=dp83932)
    pds_cards: tuple[str, ...] = ()   # PDS_CARDS keys its expansion slot takes
    slot_kind: str = "PDS"       # what that slot is: "PDS" or "NuBus"
    scsi_buses: int = 1          # 2: also an external SCSI bus (SCSI_BUSES)
    # The shared folder as a disk (classicvirtio's NuBus card, in 24-bit
    # and 32-bit mode). It takes a slot: on a model with a single PDS slot
    # a card there has to carry it too (PdsCard.host_disk_device).
    host_disk: bool = False
    # Only the sizes in ram_choices work (the RAM is soldered RAM plus
    # SIMMs of fixed sizes)
    ram_exact: bool = False
    # Built-in video memory in KB the model can have (-global
    # mac-lc-video.vram-size); the first is what Apple fitted
    vram_choices: tuple[int, ...] = ()

    @property
    def ram_min(self) -> int:
        return min(self.ram_choices) if self.ram_exact else RAM_MIN

    @property
    def screens(self) -> tuple[Screen, ...]:
        return SCREENS[self.id]


MACHINES: dict[str, MachineType] = {
    "q800": MachineType("q800", "Macintosh Quadra 800", 128, 136,
                        (8, 16, 32, 64, 128, 136), "832x624",
                        icount=False, easc=True, host_disk=True),
    "q700": MachineType("q700", "Macintosh Quadra 700", 64, 68,
                        (8, 16, 20, 32, 64, 68), "832x624",
                        icount=False, easc=False, host_disk=True),
    "q900": MachineType("q900", "Macintosh Quadra 900", 64, 256,
                        (8, 16, 20, 32, 64, 128, 256), "832x624",
                        icount=False, easc=False,
                        scsi_buses=2, host_disk=True),
    # A 33 MHz Quadra 900 with its own ROM and 2 MB of VRAM
    "q950": MachineType("q950", "Macintosh Quadra 950", 64, 256,
                        (8, 16, 20, 32, 64, 128, 256), "832x624",
                        icount=False, easc=False,
                        scsi_buses=2, host_disk=True),
    # Apple's maximum is 36 MB, but the ROM's memory sizing hangs with
    # 36 MB of QEMU's flat RAM, so 32 for now
    "lc475": MachineType("lc475", "Macintosh LC 475", 32, 32,
                         (4, 8, 16, 32), "640x480",
                         icount=False, easc=True, onboard_nic=False,
                         pds_cards=("ethernet",), host_disk=True),
    # The V8 chip: board RAM plus a pair of SIMMs, 10 MB at most. With
    # 256 KB of VRAM 640 x 480 has 16 colours; the VRAM SIMM (512 KB)
    # gives 256, and thousands on the 12" RGB. No slot card yet.
    "maclc": MachineType("maclc", "Macintosh LC", 4, 10,
                         (2, 4, 6, 10), "640x480",
                         icount=False, easc=False, onboard_nic=False,
                         ram_exact=True, vram_choices=(256, 512)),
    # 10 MB (8 MB of SIMMs) is not sized right yet
    "maclc2": MachineType("maclc2", "Macintosh LC II", 8, 8,
                          (4, 6, 8), "640x480",
                          icount=False, easc=False, onboard_nic=False,
                          ram_exact=True, vram_choices=(256, 512)),
    # Sonora: 4 MB on the board and one SIMM of 1-32 MB; 512 KB of VRAM,
    # 768 KB with the VRAM SIMM (thousands at 640 x 480)
    "maclc3": MachineType("maclc3", "Macintosh LC III", 8, 36,
                          (4, 5, 6, 8, 12, 20, 36), "640x480",
                          icount=False, easc=False, onboard_nic=False,
                          pds_cards=("ethernet",), host_disk=True,
                          ram_exact=True, vram_choices=(512, 768)),
    # 1 MB SIMMs, as Apple shipped it. 800K floppies, and 1.4 MB ones
    # with the Mac IIx ROM (the FDHD upgrade). The Mac II family has no
    # built-in Ethernet; it takes the Ethernet NB card in a NuBus slot.
    "macii": MachineType("macii", "Macintosh II", 8, 8,
                         (1, 2, 4, 8), "640x480",
                         icount=False, easc=False, onboard_nic=False,
                         pds_cards=("nubus-ethernet",), slot_kind="NuBus", host_disk=True),
    # The Mac II board with a 68030 and SIMMs of up to 16 MB; the Mac IIx
    # ROM, which reads 800K and 1.4 MB floppies. The IIcx has three slots.
    "maciix": MachineType("maciix", "Macintosh IIx", 32, 128,
                          (4, 8, 16, 32, 64, 128), "640x480",
                          icount=False, easc=False, onboard_nic=False,
                          pds_cards=("nubus-ethernet",), slot_kind="NuBus", host_disk=True),
    "maciicx": MachineType("maciicx", "Macintosh IIcx", 32, 128,
                           (4, 8, 16, 32, 64, 128), "640x480",
                           icount=False, easc=False, onboard_nic=False,
                           pds_cards=("nubus-ethernet",), slot_kind="NuBus", host_disk=True),
    # Two banks of 4-64 MB.
    "maciifx": MachineType("maciifx", "Macintosh IIfx", 32, 128,
                           (4, 8, 16, 20, 32, 64, 128), "640x480",
                           icount=False, easc=False, onboard_nic=False,
                           pds_cards=("nubus-ethernet",), slot_kind="NuBus", host_disk=True),
}



@dataclass(frozen=True)
class PdsCard:
    """A card for the machine's expansion slot (PDS or NuBus), plugged in
    with -device. A NuBus card goes in the first free slot, next to the
    video card in slot 9."""
    id: str
    label: str
    device: str                  # the QEMU device name
    nic: bool                    # takes the Network settings
    # The same card with classicvirtio's virtio devices on it as well, for
    # the shared folder disk on a model whose only slot it takes
    host_disk_device: str = ""


PDS_CARDS: dict[str, PdsCard] = {
    "ethernet": PdsCard("ethernet", "Ethernet card (SONIC)", "mac-pds-ethernet", nic=True,
                        host_disk_device="mac-pds-ethernet-virtio"),
    "nubus-ethernet": PdsCard("nubus-ethernet", "Ethernet NB card (SONIC)", "nubus-ethernet",
                              nic=True),
}
PDS_EMPTY_LABEL = "Empty"


def pds_card(card_id: str | None) -> PdsCard | None:
    return PDS_CARDS.get(card_id or "")


def pds_labels(machine_id: str) -> list[str]:
    return [PDS_EMPTY_LABEL] + [PDS_CARDS[c].label for c in machine_type(machine_id).pds_cards]


def pds_by_label(label: str) -> str:
    for c in PDS_CARDS.values():
        if c.label == label:
            return c.id
    return ""


def has_nic(machine_id: str, pds: str = "") -> bool:
    """Whether the machine has an Ethernet port the Network settings drive."""
    card = pds_card(pds)
    return machine_type(machine_id).onboard_nic or bool(card and card.nic)


# The SCSI buses, by index: the label shown, and the QEMU bus the drives go
# on. The internal bus is the one -device picks without bus=. On the
# Quadra 900 the external chip is created first, so its bus is "scsi.0".
SCSI_BUSES = (("Internal SCSI", ""), ("External SCSI", "scsi.0"))


DEFAULT_MACHINE = "q800"


def machine_ids() -> list[str]:
    return list(MACHINES)


def machine_labels() -> list[str]:
    return [t.label for t in MACHINES.values()]


def machine_by_label(label: str) -> MachineType:
    for t in MACHINES.values():
        if t.label == label:
            return t
    return MACHINES[DEFAULT_MACHINE]


def machine_type(machine_id: str | None) -> MachineType:
    return MACHINES.get(machine_id or "", MACHINES[DEFAULT_MACHINE])


def normalise_machine_id(machine_id: str | None) -> str:
    return machine_id if machine_id in MACHINES else DEFAULT_MACHINE


def screen_by_id(machine_id: str, screen_id: str) -> Screen | None:
    for s in machine_type(machine_id).screens:
        if s.id == screen_id:
            return s
    return None


def normalise_screen_id(machine_id: str, screen_id: str | None) -> str:
    """The Screen.id for *screen_id* on this model. Older records gave a depth
    too (832x624x8): the size alone picks the monitor; 800x600 always came
    up as 640x480; anything else falls back to the model's default."""
    parts = str(screen_id or "").split("x")
    sid = "x".join(parts[:2])
    sid = OLD_SCREENS.get(sid, sid)
    return sid if screen_by_id(machine_id, sid) else machine_type(machine_id).screen


def screen_by_label(machine_id: str, label: str) -> Screen | None:
    for s in machine_type(machine_id).screens:
        if s.label == label:
            return s
    return None
