"""Build the QEMU argv for a Machine and render it as run.command / run.bat.

No Tk; the only filesystem access is reading an image's first bytes. The GUI
renders for the platform it runs on; tests pass ``platform=`` explicitly
(``"darwin"``, ``"win32"``, ``"linux"``).

One argv list, two renderings (and a one-line copy for the clipboard).
"""

from __future__ import annotations

import os
import shlex

from . import paths, systems
from .model import Machine, detect_format
from .systems import DEFAULT_MOUSE_SPEED, ICOUNT_OPTION

HEADER_NOTE = "Written by Qemu-system-m68k GUI. Do not edit."

AUDIODEV_ID = "snd"
NIC_MODEL = "dp83932"            # the Quadra's built-in SONIC Ethernet


def qopt(value: str) -> str:
    """Escape a value for QEMU's key=value option parser (comma -> ,,)."""
    return str(value).replace(",", ",,")


def _path(p: str, base: str, platform: str) -> str:
    """Absolute path for *platform*; relative values resolve against *base*."""
    return paths.join_path(base, os.path.expanduser(p), platform)


def split_extra_args(text: str, platform: str = paths.HOST_PLATFORM) -> list[str]:
    """Tokenise the free-text extra arguments line. On Windows backslashes are
    path separators, not escapes, so escape processing is disabled there."""
    text = (text or "").strip()
    if not text:
        return []
    lex = shlex.shlex(text, posix=True)
    lex.whitespace_split = True
    lex.commentchars = ""
    if paths.is_windows(platform):
        lex.escape = ""
    return list(lex)


def machine_option(m: Machine, audio: bool = True) -> str:
    """The -M value: the model, its sound device's backend, and on a Quadra
    800 with Enhanced ASC turned off, easc=off."""
    parts = [m.machine]
    if audio:
        parts.append(f"audiodev={AUDIODEV_ID}")
    if m.type.easc and not m.easc:
        parts.append("easc=off")
    return ",".join(parts)


def display_option(m: Machine) -> str:
    if m.display == "cocoa" and m.swap_opt_cmd:
        return "cocoa,swap-opt-cmd=on"
    return m.display


NETDEV_ID = "net0"


def _backend(net) -> str:
    """The network backend with its own options, shared by -nic and -netdev."""
    if net.mode == "user":
        fwd = "".join(f",hostfwd={r.proto}::{r.host_port}-:{r.guest_port}"
                      for r in net.hostfwd if not r.empty)
        return f"user{fwd}"
    if net.mode in ("vmnet-bridged", "tap"):
        return f"{net.mode},ifname={qopt(net.ifname)}"
    if net.mode in ("vmnet-shared", "vmnet-host"):
        return net.mode
    raise ValueError(f"unknown network mode {net.mode!r}")


def nic_option(net) -> str:
    """The -nic value. The onboard SONIC is only wired up through a -nic
    with model=dp83932."""
    if net.mode == "none":
        return "none"
    tail = f"model={NIC_MODEL},mac={net.mac}"
    if net.mode == "user":
        fwd = "".join(f",hostfwd={r.proto}::{r.host_port}-:{r.guest_port}"
                      for r in net.hostfwd if not r.empty)
        return f"user,{tail}{fwd}"
    if net.mode in ("vmnet-bridged", "tap"):
        return f"{net.mode},ifname={qopt(net.ifname)},{tail}"
    if net.mode in ("vmnet-shared", "vmnet-host"):
        return f"{net.mode},{tail}"
    raise ValueError(f"unknown network mode {net.mode!r}")


def network_args(m: Machine) -> list[str]:
    """-nic for the built-in Ethernet; a card in the PDS slot is a -device,
    with a -netdev behind it when the network is on."""
    card = systems.pds_card(m.pds)
    if card is None or card.id not in m.type.pds_cards:
        if m.type.onboard_nic:
            return ["-nic", nic_option(m.network)]
        return ["-nic", "none"]
    args = []
    if not m.type.onboard_nic:
        args += ["-nic", "none"]
    if card.nic and m.network.mode != "none":
        args += ["-netdev", f"{_backend(m.network)},id={NETDEV_ID}",
                 "-device", f"{card.device},netdev={NETDEV_ID},mac={m.network.mac}"]
    elif card.nic:
        args += ["-device", f"{card.device},mac={m.network.mac}"]
    else:
        args += ["-device", card.device]
    return args


def drive_format(stored: str, file: str, base: str) -> str:
    """The format QEMU is told. A stored non-raw value stands; a stored "raw"
    is checked against the file, so a qcow2 picked by hand still works."""
    fmt = (stored or "").strip()
    if fmt and fmt != "raw":
        return fmt
    path = paths.join_path(base, os.path.expanduser(file), paths.HOST_PLATFORM)
    if not os.path.isfile(path):
        return "raw"
    return detect_format(path)


def _scsi_args(s, machine_dir: str, platform: str) -> list[str]:
    """-device and -drive for one SCSI ID, the way the hand-written
    launchers spell them. A drive on the external bus names its bus."""
    name = qopt(_path(s.file, machine_dir, platform))
    bus = systems.SCSI_BUSES[s.bus][1] if 0 < s.bus < len(systems.SCSI_BUSES) else ""
    on_bus = f",bus={bus}" if bus else ""
    ext = "x" if bus else ""
    if s.kind == "cdrom":
        drive_id = f"{ext}cd{s.id}"
        return ["-device", f"scsi-cd{on_bus},scsi-id={s.id},drive={drive_id}",
                "-drive", f"file={name},media=cdrom,format=raw,readonly=on,"
                          f"if=none,id={drive_id}"]
    drive_id = f"{ext}disk{s.id}"
    fmt = drive_format(s.format, s.file, machine_dir)
    return ["-device", f"scsi-hd{on_bus},scsi-id={s.id},drive={drive_id}",
            "-drive", f"file={name},media=disk,format={fmt},if=none,id={drive_id}"]


def _floppy_args(index: int, fd, machine_dir: str, platform: str) -> list[str]:
    tail = ",snapshot=on" if fd.readonly else ""
    return ["-drive", f"file={qopt(_path(fd.file, machine_dir, platform))},"
                      f"if=floppy,index={index},format=raw{tail}"]


def needs_sudo(m: Machine, platform: str = paths.HOST_PLATFORM) -> bool:
    """vmnet-* and low slirp forward ports run the binary under sudo (macOS only; never in a .bat)."""
    return (m.network.needs_sudo or m.network.low_host_port) and not paths.is_windows(platform)


def build_argv(m: Machine, qemu_dir: str, machine_dir: str,
               platform: str = paths.HOST_PLATFORM) -> list[str]:
    """The complete argv, first token = absolute path of the QEMU binary.

    *qemu_dir* is the folder the program itself lives in (ROMs are looked for
    there); *machine_dir* is the machine's own folder (its PRAM, and any
    relative image path)."""
    qd = qemu_dir
    argv: list[str] = [paths.join_path(qd, paths.qemu_binary_name(platform), platform)]

    audio = paths.resolve_audio(m.audio, platform)
    argv += ["-M", machine_option(m)]
    if m.icount:
        argv += ["-icount", ICOUNT_OPTION]
    if m.mouse_speed != DEFAULT_MOUSE_SPEED:
        argv += ["-global", f"adb-mouse.speed={int(m.mouse_speed)}"]
    argv += ["-m", str(int(m.ram_mb))]
    if m.rom:
        # No ROM chosen: the option is left out rather than pointing at a
        # guess. Starting is refused separately, with a plain message.
        argv += ["-bios", _path(m.rom, qd, platform)]
    if m.pram.strip():
        argv += ["-drive", f"file={qopt(_path(m.pram.strip(), machine_dir, platform))},"
                           "format=raw,if=mtd"]
    argv += ["-rtc", "base=localtime"]
    argv += ["-g", m.screen]
    argv += ["-display", display_option(m)]
    argv += ["-audiodev", f"{audio},id={AUDIODEV_ID}"]
    argv += network_args(m)

    buses = systems.machine_type(m.machine).scsi_buses
    for s in sorted(m.scsi, key=lambda x: (x.bus, x.id)):
        if s.file and s.bus < buses:
            argv += _scsi_args(s, machine_dir, platform)

    if systems.machine_type(m.machine).floppy:
        for index, fd in enumerate(m.floppies):
            if fd and fd.file:
                argv += _floppy_args(index, fd, machine_dir, platform)

    argv += split_extra_args(m.extra_args, platform)
    return argv


def group_options(argv: list[str]) -> list[list[str]]:
    """Group [binary, -opt, value, -opt, ...] into one list per option so
    each option lands on its own line in the rendered launcher."""
    groups: list[list[str]] = []
    for tok in argv[1:]:
        if tok.startswith("-") or not groups:
            groups.append([tok])
        else:
            groups[-1].append(tok)
    return groups


# Ask for the password ONCE. Without the keep-alive, sudo's ticket expires
# during any run longer than its timeout (5 minutes by default) and the chown
# below prompts a second time, in the middle of the guest's own output.
SUDO_KEEPALIVE = ('sudo -v\n'
                  'while true; do sudo -n true; sleep 60; '
                  'kill -0 "$$" 2>/dev/null || exit; done &\n'
                  'SUDO_KEEPALIVE_PID=$!')
CHOWN_LINE = ('kill "$SUDO_KEEPALIVE_PID" 2>/dev/null\n'
              'sudo -n chown "${SUDO_USER:-$(id -un)}" pram.img 2>/dev/null')


def render_shell(argv: list[str], sudo: bool = False) -> str:
    lines = ["#!/bin/bash",
             f"# {HEADER_NOTE}",
             'cd "$(dirname "$0")"',
             ""]
    if sudo:
        lines += [SUDO_KEEPALIVE, ""]
    lines.append(("sudo " if sudo else "") + shlex.quote(argv[0]) + " \\")
    groups = group_options(argv)
    for i, g in enumerate(groups):
        cont = " \\" if i < len(groups) - 1 else ""
        lines.append(" ".join(shlex.quote(t) for t in g) + cont)
    if sudo:
        lines += ["", CHOWN_LINE]
    return "\n".join(lines) + "\n"


def bat_quote(token: str) -> str:
    """cmd.exe quoting: whole-token double quotes when the token contains a
    space or a comma; '%' must be doubled in a .bat file."""
    t = token.replace("%", "%%")
    if (" " in t or "," in t) and not (t.startswith('"') and t.endswith('"')):
        return f'"{t}"'
    return t


BAT_TITLE = "Qemu-system-m68k"
BAT_MODE = "mode con: cols=100 lines=30"
BAT_PAUSE = "if errorlevel 1 pause"


def bat_title(name: str) -> str:
    """cmd's `title` takes the rest of the line raw, so drop anything it would
    redirect, expand or quote."""
    text = "".join(c for c in str(name or "")
                   if c.isprintable() and c not in '&<>|^"%')
    return text.strip()[:40] or BAT_TITLE


def render_bat(argv: list[str], title: str = "") -> str:
    lines = ["@echo off",
             f"rem {HEADER_NOTE}",
             f"title {bat_title(title)}",
             BAT_MODE,
             'cd /d "%~dp0"',
             "",
             bat_quote(argv[0]) + " ^"]
    groups = group_options(argv)
    for i, g in enumerate(groups):
        cont = " ^" if i < len(groups) - 1 else ""
        lines.append(" ".join(bat_quote(t) for t in g) + cont)
    lines += ["", BAT_PAUSE]
    return "\r\n".join(lines) + "\r\n"


def render_launcher(argv: list[str], platform: str = paths.HOST_PLATFORM, sudo: bool = False,
                    title: str = "") -> str:
    """The .bat never gets sudo; *sudo* only affects the shell rendering."""
    return render_bat(argv, title) if paths.is_windows(platform) else render_shell(argv, sudo)


def one_line(argv: list[str], machine_dir: str, platform: str = paths.HOST_PLATFORM,
             sudo: bool = False) -> str:
    """The command as one line to paste into a terminal: cd into the machine
    folder (QEMU writes nothing else there, but relative extra arguments
    expect it), then the emulator."""
    if paths.is_windows(platform):
        return f'cd /d {bat_quote(machine_dir)} && ' + " ".join(bat_quote(t) for t in argv)
    return f"cd {shlex.quote(machine_dir)} && " + ("sudo " if sudo else "") + shlex.join(argv)


def launcher_text(m: Machine, qemu_dir: str, machine_dir: str,
                  platform: str = paths.HOST_PLATFORM) -> str:
    return render_launcher(build_argv(m, qemu_dir, machine_dir, platform), platform,
                           needs_sudo(m, platform), m.name)


def write_launcher(m: Machine, qemu_dir: str, machine_dir: str,
                   platform: str = paths.HOST_PLATFORM):
    """Write run.command / run.bat into the machine folder; returns (path, argv)."""
    from pathlib import Path
    import stat
    argv = build_argv(m, qemu_dir, machine_dir, platform)
    text = render_launcher(argv, platform, needs_sudo(m, platform), m.name)
    path = Path(machine_dir) / paths.launcher_name(platform)
    path.write_text(text, encoding="utf-8", newline="")
    if not paths.is_windows(platform):
        st = os.stat(path)
        os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path, argv
