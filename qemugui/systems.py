"""The Macintosh models the Machine list offers, and the screens each one can
drive.

Everything that differs between models lives in the two tables below, so a
new model is one more ``MachineType`` line plus its list of screens, and a
new screen mode is one more ``Screen`` line. Nothing in ``command.py``
branches on a model's id; it reads these fields.

The only file a model names is its ROM, and only by its plain file name
(``Quadra800.rom``), which is looked for next to the emulator. Disks, CDs
and floppies are always the person's own choice.
"""

from __future__ import annotations

from dataclasses import dataclass

# -icount shift=N runs the CPU at a fixed speed (2^N ns per instruction):
# shift=6 is roughly a real 25 MHz 68040.
ICOUNT_SHIFT = 6

# Apple's own Ethernet prefix, which the Mac OS network drivers expect.
MAC_PREFIX = "08:00:07"

DEPTH_NAMES = {1: "black & white", 2: "4 colours", 4: "16 colours", 8: "256 colours",
               16: "thousands", 24: "millions"}
GREY_NAMES = {1: "black & white", 2: "4 greys", 4: "16 greys", 8: "256 greys"}


@dataclass(frozen=True)
class Screen:
    """One display mode, as -g WIDTHxHEIGHTxDEPTH.

    On the Quadra 700 the size picks the monitor (the emulated DAFB reports
    that monitor's sense code); the depth is only where the Mac starts, and
    it can switch in the Monitors control panel. 24 means "Millions"."""
    width: int
    height: int
    depth: int
    monitor: str = ""            # the Apple monitor this size is, shown first

    @property
    def id(self) -> str:
        return f"{self.width}x{self.height}x{self.depth}"

    @property
    def label(self) -> str:
        names = GREY_NAMES if "greyscale" in self.monitor else DEPTH_NAMES
        text = f"{self.width} × {self.height}, {names.get(self.depth, f'{self.depth}-bit')}"
        return f"{self.monitor} — {text}" if self.monitor else text


# The monitors each model's built-in video can drive. One line per mode.
RGB12 = 'Apple 12" RGB'
RGB13 = 'Apple 13" RGB / VGA'
PORTRAIT15 = 'Apple 15" Portrait (greyscale)'
COLOR16 = 'Apple 16" Color'
COLOR21 = 'Apple 21" Color'

SCREENS: dict[str, tuple[Screen, ...]] = {
    "q800": (
        Screen(640, 480, 1),
        Screen(640, 480, 2),
        Screen(640, 480, 4),
        Screen(640, 480, 8),
        Screen(640, 480, 24),
        Screen(800, 600, 1),
        Screen(800, 600, 2),
        Screen(800, 600, 4),
        Screen(800, 600, 8),
        Screen(800, 600, 24),
        Screen(1152, 870, 1),
        Screen(1152, 870, 2),
        Screen(1152, 870, 4),
        Screen(1152, 870, 8),
    ),
    "q700": (
        Screen(512, 384, 1, RGB12),
        Screen(512, 384, 2, RGB12),
        Screen(512, 384, 4, RGB12),
        Screen(512, 384, 8, RGB12),
        Screen(512, 384, 24, RGB12),
        Screen(640, 480, 1, RGB13),
        Screen(640, 480, 2, RGB13),
        Screen(640, 480, 4, RGB13),
        Screen(640, 480, 8, RGB13),
        Screen(640, 480, 24, RGB13),
        Screen(640, 870, 1, PORTRAIT15),
        Screen(640, 870, 2, PORTRAIT15),
        Screen(640, 870, 4, PORTRAIT15),
        Screen(640, 870, 8, PORTRAIT15),
        Screen(832, 624, 1, COLOR16),
        Screen(832, 624, 2, COLOR16),
        Screen(832, 624, 4, COLOR16),
        Screen(832, 624, 8, COLOR16),
        Screen(832, 624, 24, COLOR16),
        Screen(1152, 870, 1, COLOR21),
        Screen(1152, 870, 2, COLOR21),
        Screen(1152, 870, 4, COLOR21),
        Screen(1152, 870, 8, COLOR21),
    ),
}


@dataclass(frozen=True)
class MachineType:
    id: str                      # the -M value
    label: str
    rom: str                     # looked for next to the emulator
    ram_mb: int                  # what a new machine starts with
    ram_max: int                 # QEMU refuses more
    ram_choices: tuple[int, ...]
    screen: str                  # the Screen.id a new machine starts with
    icount: bool                 # -icount shift=ICOUNT_SHIFT on by default
    easc: bool                   # has the "easc" machine property

    @property
    def screens(self) -> tuple[Screen, ...]:
        return SCREENS[self.id]


MACHINES: dict[str, MachineType] = {
    "q800": MachineType("q800", "Macintosh Quadra 800", "Quadra800.rom", 128, 1024,
                        (8, 16, 32, 64, 128, 256, 512, 1024), "800x600x8",
                        icount=False, easc=True),
    "q700": MachineType("q700", "Macintosh Quadra 700", "Quadra700.rom", 64, 256,
                        (8, 16, 20, 32, 64, 128, 256), "832x624x8",
                        icount=True, easc=False),
}

DEFAULT_MACHINE = "q800"
RAM_MIN = 4
# Mac OS 7 and 8 are happiest at or below this; more is allowed.
RAM_COMFORTABLE = 128


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


def screen_by_label(machine_id: str, label: str) -> Screen | None:
    for s in machine_type(machine_id).screens:
        if s.label == label:
            return s
    return None
