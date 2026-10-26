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
SCREENS: dict[str, tuple[Screen, ...]] = {mid: MONITORS for mid in ("q800", "q700", "q900", "lc475")}

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
    icount: bool                 # -icount shift=ICOUNT_SHIFT on by default
    easc: bool                   # has the "easc" machine property
    floppy: bool = True          # QEMU emulates its floppy drives
    onboard_nic: bool = True     # built-in SONIC Ethernet (-nic model=dp83932)
    pds_cards: tuple[str, ...] = ()   # PDS_CARDS keys its processor-direct slot takes
    scsi_buses: int = 1          # 2: also an external SCSI bus (SCSI_BUSES)

    @property
    def screens(self) -> tuple[Screen, ...]:
        return SCREENS[self.id]


MACHINES: dict[str, MachineType] = {
    "q800": MachineType("q800", "Macintosh Quadra 800", 128, 136,
                        (8, 16, 32, 64, 128, 136), "832x624",
                        icount=False, easc=True),
    "q700": MachineType("q700", "Macintosh Quadra 700", 64, 68,
                        (8, 16, 20, 32, 64, 68), "832x624",
                        icount=True, easc=False),
    # its floppy drive sits behind an I/O processor that is not emulated yet
    "q900": MachineType("q900", "Macintosh Quadra 900", 64, 256,
                        (8, 16, 20, 32, 64, 128, 256), "832x624",
                        icount=True, easc=False, floppy=False,
                        scsi_buses=2),
    # Apple's maximum is 36 MB, but the ROM's memory sizing hangs with
    # 36 MB of QEMU's flat RAM, so 32 for now
    "lc475": MachineType("lc475", "Macintosh LC 475", 32, 32,
                         (4, 8, 16, 32), "640x480",
                         icount=False, easc=True, onboard_nic=False,
                         pds_cards=("ethernet",)),
}



@dataclass(frozen=True)
class PdsCard:
    """A card for the processor-direct slot, plugged in with -device."""
    id: str
    label: str
    device: str                  # the QEMU device name
    nic: bool                    # takes the Network settings


PDS_CARDS: dict[str, PdsCard] = {
    "ethernet": PdsCard("ethernet", "Ethernet card (SONIC)", "mac-pds-ethernet", nic=True),
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
RAM_MIN = 4


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
