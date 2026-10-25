"""The main window: the list of machines, the command line Start will run,
the emulator's output, and Start / Stop.

``start_machine()`` writes the launcher file and runs the argument list with
the machine's own folder as the working directory, its output going into
``last-run.log`` there. The emulator is always the one beside this program
(``qemu_dir()``).
"""

from __future__ import annotations

import signal
import subprocess
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from . import command, model, paths, share
from .model import Machine, Library
from .paths import Settings
from .systems import DEFAULT_MACHINE
from .ui_dialogs import (APP_TITLE, ask_name, confirm_delete, confirm_reset_pram,
                         open_folder)
from .ui_machine import MachineEditor

# The emulator's own output goes into the machine's folder.
LOG_NAME = "last-run.log"
LOG_TAIL_BYTES = 64 * 1024

# Defined by subprocess only on Windows; named here so the dispatch can be
# tested on any host.
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)


def qemu_dir() -> str:
    """The folder this program is installed in, which is the folder the
    emulator is in. There is nothing to configure."""
    return str(paths.install_dir())


class RunningMachine:
    def __init__(self, name: str, proc: subprocess.Popen, log_path: Path, argv: list[str], log_fh,
                 share_server: share.ShareServer | None = None):
        self.name = name
        self.proc = proc
        self.log_path = log_path
        self.argv = argv
        self.started = time.time()
        self.ended: float | None = None
        self._log_fh = log_fh
        self.share = share_server
        self.exit_code: int | None = None

    @property
    def pid(self) -> int:
        return self.proc.pid

    def poll(self) -> int | None:
        rc = self.proc.poll()
        if rc is not None and self.exit_code is None:
            self.exit_code = rc
            self.ended = time.time()
            if self.share:
                self.share.stop()
                self.share = None
            try:
                if self._log_fh:
                    self._log_fh.close()
            except OSError:
                pass
        return rc

    def stop(self) -> None:
        """Ask QEMU to quit (SIGTERM; it closes its disks cleanly). Like
        pulling the plug as far as the Mac is concerned."""
        if self.proc.poll() is None:
            try:
                self.proc.send_signal(signal.SIGTERM)
            except OSError:
                pass

    def kill(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass

    def uptime(self) -> float:
        return (self.ended or time.time()) - self.started


TERMINAL_STATUS = "Started in Terminal"


def start_in_terminal(m: Machine, machine_dir: Path
                      ) -> tuple[Path, share.ShareServer | None]:
    """Run the launcher in a Terminal window (macOS). Terminal is the only
    place a vmnet run can ask for the administrator password. The run cannot
    be followed from here; a shared folder stays up until the next start or
    quit."""
    machine_dir = Path(machine_dir)
    machine_dir.mkdir(parents=True, exist_ok=True)
    launcher, _argv = command.write_launcher(m, qemu_dir(), str(machine_dir))
    share_server = share.start_share(m) if m.share.ftp_on else None
    try:
        subprocess.Popen(["open", "-a", "Terminal", str(launcher)], cwd=str(machine_dir))
    except OSError:
        if share_server:
            share_server.stop()
        raise
    return launcher, share_server


def start_machine(m: Machine, machine_dir: Path) -> RunningMachine:
    """Write the launcher, start the shared folder, then run the emulator
    with the machine folder as the working directory, keeping everything it
    prints in last-run.log."""
    machine_dir = Path(machine_dir)
    machine_dir.mkdir(parents=True, exist_ok=True)
    launcher, argv = command.write_launcher(m, qemu_dir(), str(machine_dir), paths.HOST_PLATFORM)
    log_path = machine_dir / LOG_NAME
    log_path.write_text("# " + command.one_line(argv, str(machine_dir)) + "\n", encoding="utf-8")
    windows = paths.is_windows(paths.HOST_PLATFORM)
    # This program is a windowed build, so on Windows the emulator gets a
    # console of its own anyway; run the .bat in it.
    log_fh = None if windows else open(log_path, "a", encoding="utf-8")
    share_server = None
    if m.share.ftp_on:
        try:
            share_server = share.start_share(m, log_path)
        except share.ShareError:
            if log_fh:
                log_fh.close()
            raise
    try:
        if windows:
            proc = subprocess.Popen(["cmd.exe", "/c", str(launcher)], cwd=str(machine_dir),
                                    creationflags=CREATE_NEW_CONSOLE)
        else:
            proc = subprocess.Popen(argv, cwd=str(machine_dir), stdout=log_fh,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    except OSError:
        if share_server:
            share_server.stop()
        if log_fh:
            log_fh.close()
        raise
    return RunningMachine(m.name, proc, log_path, argv, log_fh, share_server)


def read_log_tail(path: Path, limit: int = LOG_TAIL_BYTES) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            data = fh.read()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace")
    if size > limit:
        text = "…\n" + text.split("\n", 1)[-1]
    return text


class MainWindow(tk.Tk):
    def __init__(self, settings: Settings, settings_path: Path | None = None):
        super().__init__()
        self.settings = settings
        self.settings_path = settings_path or paths.settings_path()
        self.library = Library()
        self.library.ensure()
        self.running: dict[str, RunningMachine] = {}
        self.finished: dict[str, RunningMachine] = {}
        self.terminal_started: dict[str, float] = {}
        self.terminal_shares: dict[str, share.ShareServer] = {}
        self.title(APP_TITLE)
        self.geometry("1100x720")
        self.minsize(880, 560)
        self.notes_name: str | None = None
        self._log_shown: tuple[str, float] | None = None
        self._build()
        self.refresh_list(select=settings.last_machine)
        self.after(1000, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._quit)

    # ---------------- layout
    def _build(self):
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="New machine…", command=self.new_machine)
        filem.add_command(label="Open the Machines folder", command=self.open_machines_folder)
        filem.add_separator()
        filem.add_command(label="Quit", command=self._quit)
        menubar.add_cascade(label="File", menu=filem)
        self.config(menu=menubar)

        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        left = ttk.Frame(pane)
        pane.add(left, weight=1)
        self.tree = ttk.Treeview(left, columns=("machine", "state"), show="headings",
                                 selectmode="browse", height=18)
        self.tree.heading("machine", text="Machine")
        self.tree.heading("state", text="")
        self.tree.column("machine", width=240, anchor="w")
        self.tree.column("state", width=80, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.on_select())
        self.tree.bind("<Double-1>", lambda _e: self.edit_machine())

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(6, 0))
        # Three dots mean another window follows. The last flag: everything
        # except New machine acts on the machine highlighted in the list, and
        # is greyed out until one is.
        spec = [("New machine…", self.new_machine, False),
                ("Duplicate", self.duplicate_machine, True),
                ("Edit…", self.edit_machine, True),
                ("Delete", self.delete_machine, True),
                ("Open machine folder", self.open_machine_folder, True),
                ("Reset PRAM", self.reset_pram, True)]
        self.machine_buttons: list[ttk.Button] = []
        for i, (label, cmd, needs_machine) in enumerate(spec):
            button = ttk.Button(btns, text=label, command=cmd)
            button.grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
            if needs_machine:
                self.machine_buttons.append(button)
        row = (len(spec) + 1) // 2
        self.start_button = ttk.Button(btns, text="Start this Mac", command=self.start_selected)
        self.start_button.grid(row=row, column=0, sticky="ew", padx=2, pady=(8, 2))
        self.stop_button = ttk.Button(btns, text="Stop", command=self.stop_selected)
        self.stop_button.grid(row=row, column=1, sticky="ew", padx=2, pady=(8, 2))
        self.terminal_button = ttk.Button(btns, text="Start in Terminal",
                                          command=self.start_selected_in_terminal)
        if paths.HOST_PLATFORM == "darwin":
            self.terminal_button.grid(row=row + 1, column=0, columnspan=2, sticky="ew",
                                      padx=2, pady=2)
        self.machine_buttons += [self.start_button, self.terminal_button]
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        right = ttk.Frame(pane)
        pane.add(right, weight=3)
        self.run_status = ttk.Label(right, text="", justify="left", font=("", 0, "bold"))
        self.run_status.pack(anchor="w", pady=(0, 6))

        head = ttk.Frame(right)
        head.pack(fill="x")
        ttk.Label(head, text="Command line constructed:").pack(side="left")
        self.copy_button = ttk.Button(head, text="Copy command", command=self.copy_command)
        self.copy_button.pack(side="right")
        self.machine_buttons.append(self.copy_button)
        self.command_line = tk.Text(right, height=13, wrap="none", font=self._mono(11))
        self.command_line.pack(fill="both", expand=True)
        self.command_line.config(state="disabled")

        ttk.Label(right, text="Output (last-run.log)").pack(anchor="w", pady=(8, 0))
        self.log_text = tk.Text(right, height=8, wrap="char", font=self._mono(10))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.config(state="disabled")

        ttk.Label(right, text="Notes").pack(anchor="w", pady=(8, 0))
        self.notes = tk.Text(right, height=4, wrap="word")
        self.notes.pack(fill="x")
        self.notes.bind("<FocusOut>", lambda _e: self.save_notes())

    @staticmethod
    def _mono(size: int):
        return ("Menlo", size) if paths.HOST_PLATFORM == "darwin" else ("Consolas", size - 1)

    @staticmethod
    def _set_text(widget: tk.Text, text: str, end: bool = False):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.config(state="disabled")
        if end:
            widget.see("end")

    def _show_notes(self, name: str | None, text: str):
        """The notes box is editable, so it has to know whose notes it holds."""
        self.notes_name = name
        self.notes.config(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)
        if name is None:
            self.notes.config(state="disabled")

    def save_notes(self):
        """Write the box back to its machine, if the user changed it."""
        name = getattr(self, "notes_name", None)
        if not name or not self.library.has_record(name):
            return
        text = self.notes.get("1.0", "end").rstrip("\n")
        try:
            m = self.library.load(name)
        except (OSError, ValueError, KeyError, TypeError):
            return
        if m.notes == text:
            return
        m.notes = text
        try:
            self.library.save(m)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"The notes for “{name}” could not be saved.\n\n{e}")

    # ---------------- list / selection
    def refresh_list(self, select: str | None = None):
        current = select or self.selected_name()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for m in self.library.load_all():
            state = "running" if m.name in self.running else ""
            self.tree.insert("", "end", iid=m.name,
                             values=(f"{m.name}   ({m.type.label})", state))
        names = self.library.names()
        if current in names:
            self.tree.selection_set(current)
            self.tree.see(current)
        elif names:
            self.tree.selection_set(names[0])
        self.on_select()

    def selected_name(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def selected_machine(self) -> Machine | None:
        name = self.selected_name()
        if not name:
            return None
        try:
            return self.library.load(name)
        except (OSError, ValueError, KeyError, TypeError) as e:
            messagebox.showerror(APP_TITLE, f"“{name}” could not be read.\n\n{e}")
            return None

    def on_select(self):
        self.save_notes()
        name = self.selected_name()
        if name:
            self.settings.last_machine = name
            self._save_settings()
        self.refresh_details()

    def command_argv(self, m: Machine) -> list[str]:
        return command.build_argv(m, qemu_dir(), str(self.library.folder(m.name)))

    def refresh_details(self):
        """The right-hand side: how it ran, the command line Start will run,
        its output, and the notes."""
        m = self.selected_machine()
        for button in self.machine_buttons:
            button.state(["disabled"] if m is None else ["!disabled"])
        if not m:
            self._set_text(self.command_line, "")
            self._set_text(self.log_text, "")
            self._show_notes(None, "")
            self.run_status.config(text="")
            self.stop_button.state(["disabled"])
            return
        folder = self.library.folder(m.name)
        try:
            text = command.launcher_text(m, qemu_dir(), str(folder))
        except Exception as e:      # never let one bad record blank the window
            text = f"({e})"
        self._set_text(self.command_line, text)
        self._show_notes(m.name, m.notes)
        self._refresh_run_status(m.name)
        self._refresh_log(m.name, force=True)

    def _refresh_log(self, name: str, force: bool = False):
        path = self.library.folder(name) / LOG_NAME
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        key = (name, mtime)
        if not force and key == self._log_shown:
            return
        self._log_shown = key
        self._set_text(self.log_text, read_log_tail(path), end=True)

    def _refresh_run_status(self, name: str):
        r = self.running.get(name) or self.finished.get(name)
        running = bool(r and r.exit_code is None)
        self.stop_button.state(["!disabled"] if running else ["disabled"])
        if not r:
            if name in self.terminal_started:
                when = time.strftime("%H:%M", time.localtime(self.terminal_started[name]))
                self.run_status.config(text=f"{TERMINAL_STATUS} ({when})"
                                       + self._share_line(name, self.terminal_shares.get(name)))
            else:
                self.run_status.config(text="Not running")
            return
        if r.exit_code is None:
            self.run_status.config(text=f"Running — {self._duration(r.uptime())}"
                                   + self._share_line(name, r.share))
        elif r.exit_code == 0:
            self.run_status.config(text=f"Stopped after {self._duration(r.uptime())}")
        else:
            self.run_status.config(
                text=f"Stopped after {self._duration(r.uptime())} — code {r.exit_code}")

    def _share_line(self, name: str, s: share.ShareServer | None) -> str:
        if not s:
            return ""
        try:
            m = self.library.load(name)
        except (OSError, ValueError, KeyError, TypeError):
            return ""
        return f"\nShared folder: {s.url_for(m.network.mode, m.network.ifname)}"

    @staticmethod
    def _duration(seconds: float) -> str:
        s = int(seconds)
        if s < 60:
            return f"{s} second{'' if s == 1 else 's'}"
        if s < 3600:
            return f"{s // 60} minute{'' if s // 60 == 1 else 's'}"
        return f"{s // 3600} hour{'' if s // 3600 == 1 else 's'} {(s % 3600) // 60} min"

    # ---------------- actions
    def new_machine(self):
        """Opens the settings window on the Machine page; nothing exists on
        disk until Save."""
        m = model.new_machine("", DEFAULT_MACHINE)
        MachineEditor(self, m, self.library, qemu_dir(), self._on_editor_save, is_new=True)

    def duplicate_machine(self):
        name = self.selected_name()
        if not name:
            return
        new_name = ask_name(self, "Duplicate", "Name:", f"{name} copy", self.library.names())
        if not new_name:
            return
        try:
            m = self.library.duplicate(name, new_name)
        except (OSError, ValueError) as e:
            messagebox.showerror("Duplicate", str(e))
            return
        self._write_launcher(m)
        self.refresh_list(select=new_name)

    def delete_machine(self):
        name = self.selected_name()
        if not name:
            return
        if name in self.running and self.running[name].poll() is None:
            messagebox.showwarning("Delete", f"“{name}” is running.")
            return
        will_go, will_stay = self.library.delete_preview(name)
        if not confirm_delete(self, name, will_go, will_stay, self.library.folder(name)):
            return
        self.library.delete(name)
        self.finished.pop(name, None)
        self.terminal_started.pop(name, None)
        self._stop_terminal_share(name)
        self.refresh_list()

    def _stop_terminal_share(self, name: str):
        s = self.terminal_shares.pop(name, None)
        if s:
            s.stop()

    def edit_machine(self):
        m = self.selected_machine()
        if not m:
            return
        MachineEditor(self, m, self.library, qemu_dir(), self._on_editor_save)

    def _on_editor_save(self, m: Machine, old_name: str):
        if old_name != m.name and old_name in self.running:
            raise ValueError("A machine cannot be renamed while it is running.")
        self.library.save(m, old_name=old_name)
        if old_name != m.name:
            self.finished.pop(old_name, None)
        self._write_launcher(m)
        self.refresh_list(select=m.name)

    def _write_launcher(self, m: Machine):
        try:
            command.write_launcher(m, qemu_dir(), str(self.library.folder(m.name)))
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"The start-up file could not be written.\n\n{e}")

    def copy_command(self):
        m = self.selected_machine()
        if not m:
            return
        argv = self.command_argv(m)
        text = command.one_line(argv, str(self.library.folder(m.name)),
                                sudo=command.needs_sudo(m))
        self.clipboard_clear()
        self.clipboard_append(text)
        self.run_status.config(text="Command copied")

    def reset_pram(self):
        """Clear what one machine remembers: zero its own pram.img.

        The Mac keeps its start-up disk and the rest of its control panel
        settings in battery-backed PRAM, and a spoiled copy is why a machine
        hangs at start-up or comes up to a flashing question mark. Zeroing the
        file is the emulated equivalent of pulling the battery. A PRAM file
        chosen from somewhere else is never touched."""
        m = self.selected_machine()
        if not m:
            return
        name = m.name
        if name in self.running and self.running[name].poll() is None:
            messagebox.showwarning("Reset PRAM", f"“{name}” is running.")
            return
        own = self.library.own_pram(m)
        if own is None:
            messagebox.showinfo("Reset PRAM",
                                f"“{name}” keeps its PRAM in {m.pram or 'no file'}, "
                                "which this program does not change.", parent=self)
            return
        if not confirm_reset_pram(self, name):
            return
        try:
            self.library.reset_pram(m)
        except OSError as e:
            messagebox.showerror("Reset PRAM", f"“{name}” could not be reset.\n\n{e}")
            return
        self.refresh_details()

    def open_machine_folder(self):
        name = self.selected_name()
        if name:
            open_folder(self.library.folder(name))

    def open_machines_folder(self):
        self.library.ensure()
        open_folder(self.library.root)

    def _ready_to_start(self, m: Machine) -> bool:
        r = self.running.get(m.name)
        if r and r.poll() is None:
            messagebox.showwarning("Start", f"“{m.name}” is already running.")
            return False
        folder = self.library.folder(m.name)
        errors, _warnings = model.validate(m, qemu_dir(), machine_dir=str(folder))
        errors += model.start_blockers(m, qemu_dir())
        if errors:
            messagebox.showerror("Start", "\n".join(f"• {e}" for e in errors))
            return False
        pram = model.pram_path(m, folder)
        if pram and not pram.exists():
            if not messagebox.askyesno("Start", f"There is no PRAM file at {pram}. "
                                                "Make a blank one?", parent=self):
                return False
            try:
                model.write_blank_pram(pram)
            except OSError as e:
                messagebox.showerror("Start", f"The PRAM file could not be made.\n\n{e}")
                return False
        return True

    def start_selected(self) -> RunningMachine | None:
        """The Start button: run the emulator from here, its output in the
        window. A vmnet or low-port machine needs sudo, so it goes to
        Terminal. Returns the RunningMachine, or None if it did not start."""
        m = self.selected_machine()
        if not m or not self._ready_to_start(m):
            return None
        if command.needs_sudo(m):
            if paths.HOST_PLATFORM != "darwin":
                messagebox.showerror("Start", "This network setting only works on a Mac.")
                return None
            self._start_terminal(m)
            return None
        try:
            r = start_machine(m, self.library.folder(m.name))
        except share.ShareError as e:
            messagebox.showerror("Start", f"The shared folder could not be started.\n\n{e}")
            return None
        except OSError as e:
            messagebox.showerror("Start", f"It could not be started.\n\n{e}")
            return None
        self.running[m.name] = r
        self.finished.pop(m.name, None)
        self.terminal_started.pop(m.name, None)
        self.refresh_list(select=m.name)
        return r

    def start_selected_in_terminal(self):
        m = self.selected_machine()
        if m and self._ready_to_start(m):
            self._start_terminal(m)

    def _start_terminal(self, m: Machine):
        self._stop_terminal_share(m.name)
        try:
            _launcher, share_server = start_in_terminal(m, self.library.folder(m.name))
        except share.ShareError as e:
            messagebox.showerror("Start", f"The shared folder could not be started.\n\n{e}")
            return
        except OSError as e:
            messagebox.showerror("Start", f"A Terminal window could not be opened.\n\n{e}")
            return
        if share_server:
            self.terminal_shares[m.name] = share_server
        self.terminal_started[m.name] = time.time()
        self.finished.pop(m.name, None)
        self.refresh_list(select=m.name)

    def stop_selected(self):
        name = self.selected_name()
        r = self.running.get(name) if name else None
        if not r or r.poll() is not None:
            return
        if not messagebox.askyesno("Stop", f"Stop “{name}” now? It is like switching the Mac "
                                           "off at the wall: shut down from the Special menu "
                                           "if you can.", icon="warning", default="no",
                                   parent=self):
            return
        r.stop()
        self.after(5000, lambda: r.kill())

    def _poll(self):
        changed = False
        for name, r in list(self.running.items()):
            if r.poll() is not None:
                self.finished[name] = r
                del self.running[name]
                changed = True
        if changed:
            self.refresh_list()
        else:
            sel = self.selected_name()
            if sel and (sel in self.running or sel in self.finished):
                self._refresh_run_status(sel)
            if sel:
                self._refresh_log(sel)
        self.after(1000, self._poll)

    # ---------------- housekeeping
    def _save_settings(self):
        try:
            self.settings.save(self.settings_path)
        except OSError:
            pass

    def _quit(self):
        self.save_notes()
        self._save_settings()
        if self.running:
            names = ", ".join(self.running)
            if not messagebox.askyesno("Quit", f"Still running: {names} — stop them and quit?"):
                return
        for name in list(self.terminal_shares):
            self._stop_terminal_share(name)
        for r in self.running.values():
            r.stop()
            if r.share:
                r.share.stop()
        self.destroy()
