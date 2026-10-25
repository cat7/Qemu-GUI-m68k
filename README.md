# Qemu-system-m68k GUI

A portable launcher for the 68k Macintosh machines of `qemu-system-m68k`:
the Macintosh Quadra 800 (`q800`), Quadra 700 (`q700`), Quadra 900 (`q900`)
and LC 475 (`lc475`). Needs real Apple ROMs. The program must sit in the same
folder as `qemu-system-m68k` (and `qemu-img`); machines are kept in a
`Machines` folder next to it, one subfolder per machine with its
`machine.json`, its `pram.img`, a `run.command` and the last run's log.

## What it sets up

- Machine model, from the table in `qemugui/systems.py` (one `MachineType`
  line per model, one `Screen` line per display mode).
- ROM (`-bios`): starts as `Quadra800.rom`, `Quadra700.rom`, `Quadra900.rom`
  (the same ROM as the 700) or `LC475.rom`, looked for next to the emulator.
- Memory (`-m`): up to 1024 MB on the Quadra 800, 256 MB on the Quadra 700
  and 900, 128 MB on the LC 475 (whose ROM sizes memory correctly only for
  the sizes offered).
- Quadra 900: keyboard and mouse go through its emulated SWIM I/O
  processor; its floppy drive does not work yet. LC 475: no built-in
  Ethernet, 1 MB of video memory, keyboard, mouse and clock through Cuda.
- PDS slot (LC 475, Machine tab): Empty or the Ethernet card
  (`-device mac-pds-ethernet`), a SONIC card that Mac OS drives with its own
  "Sonic 16" driver. It shows up as "Ethernet" in the AppleTalk and TCP/IP
  control panels.
- PRAM (`-drive ...,if=mtd`): each machine's own 512-byte `pram.img`, made
  blank when the machine is first saved; "Reset PRAM" clears it. Both
  models keep their settings there between runs.
- SCSI IDs 0 to 6: hard disk (`scsi-hd`) or CD-ROM (`scsi-cd`, read only).
  New blank disks are made with `qemu-img`. Apple HD SC Setup makes only a
  20 MB partition on them; use Drive Setup from the 7.6 or 8.0 Disk Tools
  floppy for the full size.
- Two floppy drives, 1.44 MB raw images (`if=floppy`); "Read only" throws
  changes away (`snapshot=on`). 400K/800K (GCR) disks do not work yet.
- Screen (`-g WxHxD`) from the model's monitor list; cocoa (with optional
  Option/Command swap) or sdl. On the Quadra 700 the size picks the Apple
  monitor (12" RGB, 13" RGB/VGA, 15" Portrait, 16" Color, 21" Color) and the
  depth is only where the Mac starts; it chooses its own depth in the
  Monitors control panel and keeps it in PRAM. 24 means "Millions".
- Speed limit (`-icount shift=6,align=on`): on by default for the Quadra
  700, whose ROM self tests need real-machine speed; off for the Quadra 800.
  `align=on` keeps the Mac's clock in real time; without it the clock, key
  repeat and double-click time ran about three times too fast.
- Mouse speed (`-global adb-mouse.speed=N`, percent of the host's motion,
  50 by default): macOS and Mac OS both accelerate the pointer.
- Network: slirp or vmnet (`-nic ...,model=dp83932`) with a per-machine
  card address under Apple's `08:00:07` prefix; port forwarding with slirp.
  With the LC 475's Ethernet card the same settings become
  `-netdev ...,id=net0 -device mac-pds-ethernet,netdev=net0,mac=...`.
- Sound: ASC through `-audiodev` (CoreAudio on a Mac); Enhanced ASC on the
  Quadra 800 can be turned off.
- `-rtc base=localtime`. There is no boot device setting: a bootable floppy
  or CD is used first, then the Startup Disk control panel's choice. Both
  models start up from SCSI CD-ROMs (Mac OS 8.1, System 7.5.3) and 1.44 MB
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
