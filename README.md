# Qemu-system-m68k GUI

A portable launcher for the 68k Macintosh machines of `qemu-system-m68k`:
the Macintosh Quadra 800 (`q800`), Quadra 700 (`q700`), Quadra 900 (`q900`),
LC 475 (`lc475`), Macintosh II (`macii`), IIx (`maciix`), IIcx (`maciicx`)
and IIfx (`maciifx`). Needs real Apple ROMs. The program must sit in the same
folder as `qemu-system-m68k` (and `qemu-img`); machines are kept in a
`Machines` folder next to it, one subfolder per machine with its
`machine.json`, its `pram.img`, a `run.command` and the last run's log.

## What it sets up

- Machine model, from the table in `qemugui/systems.py` (one `MachineType`
  line per model, one `Screen` line per monitor).
- ROM (`-bios`): chosen by the person; a new machine has none. (The
  Quadra 900 uses the same ROM as the 700.)
- Memory (`-m`): up to Apple's maximum: 136 MB on the Quadra 800, 68 MB on
  the Quadra 700, 256 MB on the Quadra 900. The LC 475's is 36 MB, but its
  ROM's memory sizing hangs at 36 MB, so 32 MB for now. Macintosh II:
  1 to 8 MB. IIx, IIcx and IIfx: 4 to 128 MB.
- Quadra 900 and IIfx: keyboard, mouse and floppy drive go through the
  emulated SWIM I/O processor. LC 475: no built-in
  Ethernet, 1 MB of video memory, keyboard, mouse and clock through Cuda.
- Macintosh II, IIx, IIcx and IIfx: no built-in video; QEMU puts its own
  NuBus video card in slot 9 (any of the listed screen sizes, 1 to 32 bits
  per pixel). No built-in Ethernet. They need real-machine speed. The Mac II takes
  the Mac II ROM (800K floppies) or the Mac IIx ROM (800K and 1.4 MB
  floppies); the IIx and IIcx use the Mac IIx ROM.
- PDS slot (LC 475, Machine tab): Empty or the Ethernet card
  (`-device mac-pds-ethernet`), a SONIC card that Mac OS drives with its own
  "Sonic 16" driver. It shows up as "Ethernet" in the AppleTalk and TCP/IP
  control panels.
- NuBus slot (Mac II, IIx, IIcx, IIfx, Machine tab): Empty or the Ethernet
  NB card (`-device nubus-ethernet`), a SONIC card with its own buffer RAM
  that Mac OS drives with its "Sonic 16 NB" driver. It goes in the first
  free slot after the video card. Open Transport needs a 68030, so on the
  Mac II (68020) the card needs classic AppleTalk and MacTCP instead.
- PRAM (`-drive ...,if=mtd`): each machine's own 512-byte `pram.img`, made
  blank when the machine is first saved; "Reset PRAM" clears it. Both
  models keep their settings there between runs.
- SCSI IDs 0 to 6: hard disk (`scsi-hd`) or CD-ROM (`scsi-cd`).
  The Quadra 900 also has its external SCSI bus, IDs 0 to 6 again
  (`bus=scsi.0`); its internal bus is the one drives go on without `bus=`.
  Two bootable system CDs at once can leave the Mac at the flashing "?"
  (the older CD's driver takes over both drives); this happens on one bus
  too.
  New blank disks are made with `qemu-img`.
- Two floppy drives, raw 400K, 800K and 1.44 MB images (`if=floppy`);
  "Read only" throws changes away (`snapshot=on`). The Mac can initialize
  all of them; a two-sided (800K) format of a 400K image makes it 800K.
- Monitor (`-g WxH`): the Apple monitor connected to the built-in video,
  the same five on every model: 12" RGB (512 × 384), 13" RGB/VGA
  (640 × 480), 15" Portrait (640 × 870), 16" Color (832 × 624) and 21"
  Color (1152 × 870); the size picks the monitor. Colour depth is chosen in
  Mac OS (Monitors control panel), which keeps it in PRAM. cocoa (with
  optional Option/Command swap) or sdl.
- Speed limit (`-icount shift=6,align=on`): on by default for the Quadra
  700, whose ROM self tests need real-machine speed; off for the Quadra 800.
  `align=on` keeps the Mac's clock in real time; without it the clock, key
  repeat and double-click time ran about three times too fast.
- Mouse speed (`-global adb-mouse.speed=N`, percent of the host's motion,
  50 by default): macOS and Mac OS both accelerate the pointer.
- Network: slirp or vmnet (`-nic ...,model=dp83932`) with a per-machine
  card address under Apple's `08:00:07` prefix; port forwarding with slirp.
  With an Ethernet card (LC 475, Mac II family) the same settings become
  `-netdev ...,id=net0 -device mac-pds-ethernet,netdev=net0,mac=...`
  (`nubus-ethernet` on the Mac II family).
- Sound: ASC through `-audiodev` (CoreAudio on a Mac); Enhanced ASC on the
  Quadra 800 can be turned off.
- `-rtc base=localtime`. There is no boot device setting. Start-up order:
  1. bootable floppy, 2. CD-ROM with highest SCSI ID (unless another disk
  is selected through the Startup Disk control panel). The models start up from SCSI CD-ROMs (Mac OS 8.1, System 7.5.3) and 1.44 MB
  floppies; a non-bootable CD mounts once a system with the Apple CD-ROM
  extension is running.
- Shared folder over FTP (pyftpdlib): with slirp the Mac reaches it at
  `ftp://10.0.2.2/` (`:2121` when port 21 is taken), passive mode, names in
  Mac Roman.

The main window shows the command line, copies it as one line, starts the
machine (its output shown from `last-run.log`) and stops it. "Start in
Terminal" runs `run.command` in Terminal instead; vmnet and host ports
below 1024 always go that way, since they need `sudo`.

## Requirements

- To run from source: Python 3.11+ with tkinter, plus `pyftpdlib` for the
  shared folder (`python -m pip install pyftpdlib`).
- To build a distributable bundle: PyInstaller, with `pyftpdlib` installed
  in the same Python.

## Run from source

    python qemu_gui.py

(from a folder holding `qemu-system-m68k`, or put the sources there).

## Build on macOS

Needs a universal2 python.org framework build of Python (Homebrew's Python
is arch-specific and has no tkinter; Apple's `/usr/bin/python3` is arm64e
and not redistributable):

    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
        -m PyInstaller --noconfirm QemuGUI.spec

Result: `dist/Qemu-system-m68k GUI.app`. Put it in the folder that holds
`qemu-system-m68k`. For a build that runs only on the building machine's
architecture, prefix the command with `QEMUGUI_TARGET_ARCH=arm64` (or
`x86_64`).

## Tests

    python -m pytest tests            # or: python -m unittest discover -s tests

`tests/test_live.py` runs the real emulator headless for 20 seconds per
model with the generated command line (plus `-display none` and
`-snapshot`, so no image is changed); it is skipped unless asked for:

    QEMUGUI_LIVE=1 QEMUGUI_QEMU_DIR=/Applications/Qemu-system-m68k \
    QEMUGUI_Q800_DISK=/path/to/system8.img QEMUGUI_Q700_DISK=/path/to/system7.1.img \
        python -m pytest -s tests/test_live.py
