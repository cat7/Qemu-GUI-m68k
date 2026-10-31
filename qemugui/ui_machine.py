"""The machine editor: Machine, Display, Drives, Network & sound, Shared
folder, Advanced.

Two rules with teeth:

* **No disk is ever filled in for you.** Hard disks, CDs and floppies start
  empty and stay empty until they are chosen. The ROM starts as the model's
  own ROM next to the emulator, and the PRAM as the machine's own pram.img.
* A file field is one control: a path can be typed or pasted straight into
  it, and double-clicking it opens the chooser.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from . import model, paths, systems
from .model import Machine, ScsiDrive, Floppy, Network, Share
from .systems import ICOUNT_OPTION, machine_labels, machine_by_label, machine_type
from .ui_dialogs import show_validation, CreateDiskDialog, ToolTip

KIND_LABELS = {"": "Empty", "disk": "Hard disk", "cdrom": "CD-ROM"}
KIND_BY_LABEL = {v: k for k, v in KIND_LABELS.items()}
IMAGE_TYPES = [("Hard disks and CDs", "*.img *.dsk *.hfv *.qcow2 *.iso *.toast *.cdr *.raw"),
               ("Every file", "*")]
ROM_TYPES = [("ROM files", "*.rom *.ROM *.bin"), ("Every file", "*")]
PRAM_TYPES = [("PRAM files", "*.img *.bin"), ("Every file", "*")]
FLOPPY_TYPES = [("Floppy disks", "*.img *.dsk *.image"), ("Every file", "*")]
CDROM_EXTS = {".iso", ".toast", ".cdr"}

GREY = "gray"

EDITOR_WIDTH = 760

ICOUNT_TIP = (f"Adds -icount {ICOUNT_OPTION}: the emulated CPU runs at a fixed speed "
              "close to the real machine instead of as fast as the host allows, and the "
              "Mac's clock keeps real time. The ROMs no longer need it: QEMU slows the "
              "CPU by itself while they time their start-up loops. Turn it on for "
              "software that times itself against the clock and fails or runs too fast "
              "otherwise (some system versions stop with a divide-by-zero error, games "
              "can run too fast). It makes the Mac slower.")
EASC_TIP = ("The Quadra 800 has Apple's Enhanced ASC sound chip. Untick to emulate the "
            "original ASC instead, for software that only knows the older chip.")
SWAP_TIP = "Swap the Option and Command keys, for a PC keyboard."
MOUSE_TIP = ("How much of the host's mouse motion reaches the Mac. macOS and Mac OS both "
             "accelerate the pointer, so 100 % feels too fast; lower it if double-clicks "
             "are hard to hit. The Mac's Mouse control panel adds its own setting on top.")
PRAM_TIP = ("The Mac's battery-backed settings: start-up disk, date and time format, "
            "sound, monitor depth. Kept in this file between runs; empty = forgotten "
            "every time.")


def browse_file(parent, var: tk.StringVar, filetypes, fallback: Path | str | None = None) -> str:
    start = paths.browse_start_dir(var.get(), fallback)
    f = filedialog.askopenfilename(parent=parent, initialdir=str(start), filetypes=filetypes)
    if f:
        var.set(f)
        return f
    return ""



def _speed_label(v: int) -> str:
    return f"{v} %" + (" (default)" if v == systems.DEFAULT_MOUSE_SPEED else "")


def _speed_value(label: str, fallback: int) -> int:
    try:
        return int(label.split()[0])
    except (IndexError, ValueError):
        return fallback


def _vram_label(kb: int) -> str:
    return f"{kb // 1024} MB" if kb >= 1024 and kb % 1024 == 0 else f"{kb} KB"


def _vram_value(label: str) -> int:
    try:
        n, unit = label.split()[:2]
        return int(n) * (1024 if unit == "MB" else 1)
    except ValueError:
        return 0

class FilePicker:
    """One control for one file: type a path into it, paste one into it, or
    double-click it to go and find one."""

    def __init__(self, master, var: tk.StringVar, filetypes, width: int = 40, fallback=None,
                 on_pick=None):
        self.var = var
        self.filetypes = filetypes
        self.fallback = fallback
        self.on_pick = on_pick
        self.entry = ttk.Entry(master, textvariable=var, width=width)
        self.entry.bind("<Double-Button-1>", self._browse)
        var.trace_add("write", lambda *_a: self._refresh())
        self._refresh()

    def grid(self, **kw) -> "FilePicker":
        self.entry.grid(**kw)
        return self

    def _refresh(self) -> None:
        if self.var.get():
            # a long path is shown from its end, where the file's name is
            self.entry.xview_moveto(1.0)

    def _browse(self, _e=None):
        fb = self.fallback() if callable(self.fallback) else self.fallback
        chosen = browse_file(self.entry.winfo_toplevel(), self.var, self.filetypes, fb)
        if chosen and self.on_pick:
            self.on_pick(chosen)
        return "break"


class DriveRow:
    """One SCSI ID: what is in it and which file it is."""

    def __init__(self, master, row: int, sid: int, fallback=None, bus: int = 0):
        self.sid = sid
        self.bus = bus
        self.kind = tk.StringVar(value=KIND_LABELS[""])
        self.file = tk.StringVar()
        self.format = tk.StringVar(value="raw")
        ttk.Label(master, text=model.scsi_name(sid)).grid(row=row, column=0, sticky="w",
                                                         padx=(0, 4), pady=1)
        cb = ttk.Combobox(master, textvariable=self.kind, values=list(KIND_LABELS.values()),
                          state="readonly", width=9)
        cb.grid(row=row, column=1, padx=2, pady=1)
        cb.bind("<<ComboboxSelected>>", self._kind_changed)
        self.picker = FilePicker(master, self.file, IMAGE_TYPES, width=40,
                                 fallback=fallback, on_pick=self._file_picked)
        self.picker.grid(row=row, column=2, sticky="ew", padx=2, pady=1)
        self.file.trace_add("write", lambda *_a: self._infer_kind())
        self.format_cb = ttk.Combobox(master, textvariable=self.format, values=model.FORMATS,
                                      state="readonly", width=6)
        self.format_cb.grid(row=row, column=3, padx=2)

    def _file_picked(self, path: str):
        """Only a file chosen through the dialog re-detects the format, so a
        format set by hand survives until another file is chosen."""
        self.format.set(model.detect_format(path))

    def _infer_kind(self):
        """A file chosen while the position still says "Empty" would be
        dropped on save, so work out from the file name what it is."""
        if KIND_BY_LABEL[self.kind.get()] or not self.file.get().strip():
            return
        ext = Path(self.file.get().strip()).suffix.lower()
        self.kind.set(KIND_LABELS["cdrom" if ext in CDROM_EXTS else "disk"])
        self._kind_changed()

    def _kind_changed(self, _e=None):
        k = KIND_BY_LABEL[self.kind.get()]
        if not k:
            # Choosing "Empty" means it: clear the position, or the file left
            # behind would be re-read as a drive the moment it is saved.
            self.file.set("")
            self.format.set("raw")
        if k == "cdrom":
            self.format.set("raw")
        self.format_cb.config(state="readonly" if k == "disk" else "disabled")

    def set(self, d: ScsiDrive | None):
        self.kind.set(KIND_LABELS[d.kind if d else ""])
        self.file.set(d.file if d else "")
        self.format.set((d.format if d else "raw") or "raw")
        self.format_cb.config(state="readonly" if d and d.kind == "disk" else "disabled")

    def get(self) -> ScsiDrive | None:
        self._infer_kind()
        k = KIND_BY_LABEL[self.kind.get()]
        if not k or not self.file.get().strip():
            return None
        return ScsiDrive(id=self.sid, kind=k, file=self.file.get().strip(),
                         format=self.format.get() or "raw" if k == "disk" else "raw",
                         bus=self.bus)


def _set_state(widget, state: str):
    """Set a widget's state, and its children's for compound widgets."""
    try:
        widget.config(state=state)
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        _set_state(child, state)


class FloppyRow:
    def __init__(self, master, row: int, index: int, fallback=None):
        self.file = tk.StringVar()
        self.readonly = tk.BooleanVar(value=False)
        ttk.Label(master, text=model.floppy_name(index) + ":").grid(
            row=row, column=0, sticky="w", padx=(0, 4), pady=1)
        self.picker = FilePicker(master, self.file, FLOPPY_TYPES, width=40,
                                 fallback=fallback)
        self.picker.grid(row=row, column=1, sticky="ew", padx=2, pady=1)
        ro = ttk.Checkbutton(master, text="Read only", variable=self.readonly)
        ro.grid(row=row, column=2, sticky="w", padx=(6, 0))
        self.widgets = [self.picker.entry, ro]
        ToolTip(ro, "The Mac may write to the disk while it runs, but every change is "
                    "thrown away when it stops (snapshot=on). Use it for install disks.")

    def set(self, fd: Floppy | None):
        self.file.set(fd.file if fd else "")
        self.readonly.set(fd.readonly if fd else False)

    def enable(self, on: bool):
        for w in self.widgets:
            _set_state(w, "normal" if on else "disabled")

    def get(self) -> Floppy | None:
        f = self.file.get().strip()
        return Floppy(f, self.readonly.get()) if f else None


class MachineEditor(tk.Toplevel):
    """One machine's settings. ``on_save(machine, old_name)`` runs after
    checking. With ``is_new`` the same window opens fresh; nothing exists on
    disk until Save."""

    def __init__(self, parent, machine: Machine, library: model.Library, qemu_dir: str, on_save,
                 is_new: bool = False):
        super().__init__(parent)
        self.machine = machine.copy()
        self.old_name = machine.name
        self.is_new = is_new
        self.library = library
        self.qemu_dir = qemu_dir
        self.on_save = on_save
        self.title("New machine" if is_new else f"{machine.name} — settings")
        self.resizable(True, True)
        self.transient(parent)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self._build_machine()
        self._build_display()
        self._build_drives()
        self._build_net_audio()
        self._build_share()
        self._build_advanced()

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=6, pady=(0, 6))
        self.msg = ttk.Label(bar, text="", foreground=GREY, wraplength=EDITOR_WIDTH - 200)
        self.msg.pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=2)
        ttk.Button(bar, text="Save", command=self.save).pack(side="right", padx=2)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.load(self.machine)
        self._size_window()
        self._centre_on(parent)
        self.nb.select(0)                       # the Machine page, always first
        self.name_entry.focus_set()

    def _size_window(self):
        """No taller than the screen it has to fit on."""
        self.update_idletasks()
        height = min(self.winfo_reqheight(), max(400, self.winfo_screenheight() - 160))
        self.geometry(f"{max(EDITOR_WIDTH, self.winfo_reqwidth())}x{height}")
        self.minsize(640, 400)

    def _centre_on(self, parent):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            w, h = EDITOR_WIDTH, self.winfo_reqheight()
        try:
            top = parent.winfo_toplevel()
            top.update_idletasks()
            x = top.winfo_rootx() + (top.winfo_width() - w) // 2
            y = top.winfo_rooty() + (top.winfo_height() - h) // 2
        except tk.TclError:
            return
        x = max(0, min(x, self.winfo_screenwidth() - w))
        y = max(0, min(y, self.winfo_screenheight() - h - 40))
        self.geometry(f"{w}x{h}+{x}+{y}")

    def machine_folder(self) -> Path:
        """Where this machine's own files live, named after the machine."""
        name = self.name_var.get().strip() or self.old_name
        return self.library.folder(name) if name else self.library.root

    @property
    def machine_id(self) -> str:
        return machine_by_label(self.type_var.get()).id

    # ---------------- tabs
    def _tab(self, title: str) -> ttk.Frame:
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text=title)
        return f

    @staticmethod
    def _heading(f, row: int, text: str, pady=(0, 4)):
        label = ttk.Label(f, text=text, font=("", 0, "bold"))
        label.grid(row=row, column=0, columnspan=4, sticky="w", pady=pady)
        return label

    def _build_machine(self):
        f = self._tab("Machine")
        f.columnconfigure(1, weight=1)
        r = 0
        ttk.Label(f, text="Name:").grid(row=r, column=0, sticky="w", pady=4)
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(f, textvariable=self.name_var, width=40)
        self.name_entry.grid(row=r, column=1, columnspan=2, sticky="ew", pady=4)
        r += 1
        ttk.Label(f, text="Machine:").grid(row=r, column=0, sticky="w", pady=4)
        self.type_var = tk.StringVar()
        type_box = ttk.Combobox(f, textvariable=self.type_var, values=machine_labels(),
                                state="readonly", width=26)
        type_box.grid(row=r, column=1, sticky="w", pady=4)
        type_box.bind("<<ComboboxSelected>>", self._type_chosen)
        r += 1
        ttk.Label(f, text="Memory (MB):").grid(row=r, column=0, sticky="w", pady=4)
        self.ram_var = tk.StringVar()
        self.ram_cb = ttk.Combobox(f, textvariable=self.ram_var, width=10)
        self.ram_cb.grid(row=r, column=1, sticky="w", pady=4)
        r += 1
        self.ram_hint = ttk.Label(f, text="", foreground=GREY)
        self.ram_hint.grid(row=r, column=1, columnspan=2, sticky="w")
        r += 1
        self.pds_label = ttk.Label(f, text="PDS slot:")
        self.pds_label.grid(row=r, column=0, sticky="w", pady=4)
        self.pds_var = tk.StringVar(value=systems.PDS_EMPTY_LABEL)
        self.pds_cb = ttk.Combobox(f, textvariable=self.pds_var, state="readonly", width=26,
                                   values=[systems.PDS_EMPTY_LABEL])
        self.pds_cb.grid(row=r, column=1, sticky="w", pady=4)
        self.pds_cb.bind("<<ComboboxSelected>>", lambda _e: self._update_net_hint())
        r += 1
        self.pds_hint = ttk.Label(f, text="", foreground=GREY)
        self.pds_hint.grid(row=r, column=1, columnspan=2, sticky="w")
        r += 1
        ttk.Label(f, text="ROM:").grid(row=r, column=0, sticky="w", pady=4)
        self.rom_var = tk.StringVar()
        FilePicker(f, self.rom_var, ROM_TYPES, width=40,
                   fallback=lambda: self.qemu_dir).grid(row=r, column=1, columnspan=2,
                                                        sticky="ew", pady=4)
        r += 1
        pl = ttk.Label(f, text="PRAM file:")
        pl.grid(row=r, column=0, sticky="w", pady=4)
        ToolTip(pl, PRAM_TIP)
        self.pram_var = tk.StringVar()
        FilePicker(f, self.pram_var, PRAM_TYPES, width=30,
                   fallback=self.machine_folder).grid(row=r, column=1, sticky="ew", pady=4)
        ttk.Button(f, text="New blank PRAM…", command=self._new_pram).grid(
            row=r, column=2, sticky="w", padx=(6, 0))
        r += 1
        ttk.Label(f, text="Parameter RAM is kept in the machine folder",
                  foreground=GREY).grid(row=r, column=1, columnspan=2, sticky="w")
        r += 1
        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="ew", pady=10)
        r += 1
        self._heading(f, r, "Speed")
        r += 1
        self.icount_var = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(f, text="Run at real-machine speed",
                             variable=self.icount_var)
        cb.grid(row=r, column=0, columnspan=3, sticky="w")
        ToolTip(cb, ICOUNT_TIP)

    def _new_pram(self):
        """Point the machine at its own pram.img and make it blank: offered,
        never done behind the person's back if a PRAM is already there."""
        if not self.name_var.get().strip():
            messagebox.showinfo("New blank PRAM", "Give this machine a name first.", parent=self)
            return
        target = self.machine_folder() / model.PRAM_NAME
        if target.exists():
            if not messagebox.askyesno(
                    "New blank PRAM",
                    f"{target} is already there. Clear it, so the Mac forgets its start-up "
                    "disk and control panel settings?", icon="warning", default="no",
                    parent=self):
                return
            try:
                target.write_bytes(b"\0" * model.PRAM_SIZE)
            except OSError as e:
                messagebox.showerror("New blank PRAM", str(e), parent=self)
                return
        else:
            try:
                model.write_blank_pram(target)
            except OSError as e:
                messagebox.showerror("New blank PRAM", str(e), parent=self)
                return
        self.pram_var.set(model.PRAM_NAME)
        self.msg.config(text=f"Blank PRAM: {target}")

    def _build_display(self):
        f = self._tab("Display")
        f.columnconfigure(1, weight=1)
        self._heading(f, 0, "Monitor")
        ttk.Label(f, text="Screen:").grid(row=1, column=0, sticky="w", pady=4)
        self.screen_var = tk.StringVar()
        self.screen_cb = ttk.Combobox(f, textvariable=self.screen_var, state="readonly", width=34)
        self.screen_cb.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(f, text="Starts at this size. Change resolution and colours in Mac OS "
                          "(Monitors control panel)",
                  foreground=GREY).grid(row=2, column=1, sticky="w")
        # built-in video memory, on the models that had a VRAM upgrade
        vf = ttk.Frame(f)
        vf.grid(row=1, column=2, sticky="w", padx=(12, 0))
        ttk.Label(vf, text="Video memory:").grid(row=0, column=0, sticky="w")
        self.vram_var = tk.StringVar()
        self.vram_cb = ttk.Combobox(vf, textvariable=self.vram_var, state="readonly", width=8)
        self.vram_cb.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.vram_frame = vf
        ttk.Separator(f).grid(row=3, column=0, columnspan=3, sticky="ew", pady=10)
        self._heading(f, 4, "Display type")
        ttk.Label(f, text="Display:").grid(row=5, column=0, sticky="w", pady=4)
        self.display_var = tk.StringVar()
        dcb = ttk.Combobox(f, textvariable=self.display_var,
                           values=list(model.displays_for_host()), state="readonly", width=10)
        dcb.grid(row=5, column=1, sticky="w", pady=4)
        dcb.bind("<<ComboboxSelected>>", self._display_changed)
        self.swap_var = tk.BooleanVar(value=False)
        self.swap_cb = ttk.Checkbutton(f, text="Swap Option and Command (cocoa)",
                                       variable=self.swap_var)
        self.swap_cb.grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ToolTip(self.swap_cb, SWAP_TIP)
        ml = ttk.Label(f, text="Mouse speed:")
        ml.grid(row=7, column=0, sticky="w", pady=(10, 4))
        ToolTip(ml, MOUSE_TIP)
        self.mouse_var = tk.StringVar()
        mcb = ttk.Combobox(f, textvariable=self.mouse_var, state="readonly", width=10,
                           values=[_speed_label(v) for v in systems.MOUSE_SPEEDS])
        mcb.grid(row=7, column=1, sticky="w", pady=(10, 4))
        ToolTip(mcb, MOUSE_TIP)

    def _scsi_table(self, parent, row: int, bus: int) -> list:
        """IDs 0-6 of one SCSI bus, and 7, the Mac itself."""
        scsi = ttk.Frame(parent)
        scsi.grid(row=row, column=0, sticky="ew")
        scsi.columnconfigure(2, weight=1)
        for c, h in enumerate(("ID", "", "Image", "Format")):
            ttk.Label(scsi, text=h, foreground=GREY).grid(row=0, column=c, sticky="w", padx=4)
        rows = [DriveRow(scsi, sid + 1, sid, fallback=self.machine_folder, bus=bus)
                for sid in model.SCSI_IDS]
        self_row = model.SCSI_SELF_ID + 1
        ttk.Label(scsi, text=model.scsi_name(model.SCSI_SELF_ID)).grid(
            row=self_row, column=0, sticky="w", padx=(0, 4), pady=1)
        ttk.Label(scsi, text=model.SCSI_SELF_LABEL, foreground=GREY).grid(
            row=self_row, column=1, columnspan=3, sticky="w", padx=2, pady=1)
        return rows

    def _display_changed(self, _e=None):
        self.swap_cb.config(state="normal" if self.display_var.get() == "cocoa" else "disabled")

    def _build_drives(self):
        f = self._tab("Drives")
        f.columnconfigure(0, weight=1)
        r = 0
        self.scsi_heading = self._heading(f, r, "SCSI")
        r += 1
        self.scsi_rows = self._scsi_table(f, r, 0)
        r += 1
        # The second bus (Quadra 900): shown only for a model that has one
        self.ext_scsi = ttk.Frame(f)
        self.ext_scsi.grid(row=r, column=0, sticky="ew", pady=(8, 0))
        self.ext_scsi.columnconfigure(0, weight=1)
        self._heading(self.ext_scsi, 0, model.scsi_bus_name(1))
        self.ext_rows = self._scsi_table(self.ext_scsi, 1, 1)
        r += 1
        ttk.Label(f, text="Standard IDs: Hard disk ID 0, CD-ROM ID 3",
                  foreground=GREY).grid(row=r, column=0, sticky="w", padx=4, pady=(6, 0))
        r += 1
        bar = ttk.Frame(f)
        bar.grid(row=r, column=0, sticky="ew", pady=(8, 2))
        have_img = paths.qemu_img_binary().is_file()
        ttk.Button(bar, text="Create new disk image…", command=self._create_disk,
                   state=("normal" if have_img else "disabled")).pack(side="left", padx=4)
        if not have_img:
            ttk.Label(bar, text=f"{paths.qemu_img_name()} not found",
                      foreground=GREY).pack(side="left", padx=6)
        r += 1
        ttk.Separator(f).grid(row=r, column=0, sticky="ew", pady=8)
        r += 1
        self._heading(f, r, "Floppy")
        r += 1
        fd = ttk.Frame(f)
        fd.grid(row=r, column=0, sticky="ew")
        fd.columnconfigure(1, weight=1)
        self.floppy_rows = [FloppyRow(fd, i, i, fallback=self.machine_folder)
                            for i in range(model.FLOPPY_DRIVES)]
        r += 1
        ttk.Label(f, text="Raw 400K, 800K, 720K and 1.44 MB images.",
                  foreground=GREY).grid(row=r, column=0, sticky="w", padx=4, pady=(6, 0))
        r += 1
        ttk.Label(f, text="Start-up order: 1. bootable floppy, 2. CD-ROM with highest SCSI "
                          "ID (unless another disk is selected through the Startup Disk "
                          "control panel)",
                  foreground=GREY, wraplength=EDITOR_WIDTH - 60, justify="left").grid(
            row=r, column=0, sticky="w", padx=4, pady=(4, 0))

    def _build_net_audio(self):
        f = self._tab("Network & sound")
        hf = ttk.Frame(f)
        hf.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))
        ttk.Label(hf, text="Network", font=("", 0, "bold")).grid(row=0, column=0, sticky="w")
        self.net_hint = ttk.Label(hf, text="", foreground=GREY)
        self.net_hint.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(f, text="Connection:").grid(row=1, column=0, sticky="w")
        self.net_mode = tk.StringVar(value=model.network_mode_label("user"))
        self.net_mode_cb = ttk.Combobox(f, textvariable=self.net_mode, state="readonly", width=18,
                                        values=model.network_labels_for_host(paths.HOST_PLATFORM))
        self.net_mode_cb.grid(row=1, column=1, sticky="w")
        self.net_mode_cb.bind("<<ComboboxSelected>>", self._net_mode_changed)
        ttk.Label(f, text="vmnet needs the administrator password",
                  foreground=GREY).grid(row=1, column=2, sticky="w", padx=6)
        self.ifname_label = ttk.Label(f, text=model.ifname_label(paths.HOST_PLATFORM))
        self.ifname_label.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.ifname_var = tk.StringVar()
        self.ifname_entry = ttk.Entry(f, textvariable=self.ifname_var, width=28)
        self.ifname_entry.grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(f, text="Card MAC address:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.mac_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.mac_var, width=22).grid(
            row=3, column=1, sticky="w", pady=(6, 0))
        ttk.Button(f, text="New address", command=lambda: self.mac_var.set(model.random_mac())
                   ).grid(row=3, column=2, sticky="w", padx=6, pady=(6, 0))
        ff = ttk.Frame(f)
        ff.grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(ff, text="Port forwarding", font=("", 0, "bold")).grid(
            row=0, column=0, columnspan=5, sticky="w")
        ttk.Label(ff, text="For Slirp networking only. When forwarding ports below 1024 the "
                           "administrator password is needed",
                  foreground=GREY).grid(row=1, column=0, columnspan=5, sticky="w", pady=(0, 4))
        for c, t in enumerate(("Protocol", "Host port", "Guest port")):
            ttk.Label(ff, text=t, foreground=GREY).grid(row=2, column=c, sticky="w", padx=(0, 6))
        self.fwd_rows = []
        for i in range(model.HOSTFWD_ROWS):
            proto = tk.StringVar(value="tcp")
            hp, gp = tk.StringVar(), tk.StringVar()
            w = [ttk.Combobox(ff, textvariable=proto, state="readonly", width=5,
                              values=list(model.HOSTFWD_PROTOS)),
                 ttk.Entry(ff, textvariable=hp, width=8),
                 ttk.Entry(ff, textvariable=gp, width=8)]
            for c, x in enumerate(w):
                x.grid(row=3 + i, column=c, sticky="w", padx=(0, 6), pady=1)
            self.fwd_rows.append((proto, hp, gp, w))
        ttk.Separator(f).grid(row=5, column=0, columnspan=3, sticky="ew", pady=10)
        self._heading(f, 6, "Sound")
        self.audio_var = tk.StringVar(value="default")
        ttk.Radiobutton(f, text=model.default_audio_label(paths.HOST_PLATFORM),
                        variable=self.audio_var, value="default").grid(
            row=7, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(f, text="SDL", variable=self.audio_var, value="sdl").grid(
            row=8, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(f, text="None", variable=self.audio_var, value="none").grid(
            row=9, column=0, columnspan=3, sticky="w")
        self.easc_var = tk.BooleanVar(value=True)
        self.easc_cb = ttk.Checkbutton(f, text="Enhanced ASC (Quadra 800)",
                                       variable=self.easc_var)
        self.easc_cb.grid(row=10, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ToolTip(self.easc_cb, EASC_TIP)

    def _net_mode_changed(self, _e=None):
        mode = model.network_mode_by_label(self.net_mode.get())
        if mode in model.NETWORK_MODES_WITH_IFNAME:
            self.ifname_entry.config(state="normal")
            if not self.ifname_var.get():
                self.ifname_var.set(model.default_ifname(mode, paths.HOST_PLATFORM))
        else:
            self.ifname_entry.config(state="disabled")
        for *_v, widgets in self.fwd_rows:
            for i, w in enumerate(widgets):
                w.config(state=("readonly" if i == 0 else "normal") if mode == "user"
                         else "disabled")

    def _build_share(self):
        f = self._tab("Shared folder")
        f.columnconfigure(1, weight=1)
        self._heading(f, 0, "Shared folder")
        ttk.Label(f, text="Folder:").grid(row=1, column=0, sticky="w", pady=4)
        self.share_folder_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.share_folder_var, width=40).grid(
            row=1, column=1, sticky="ew", pady=4)
        ttk.Button(f, text="Choose…", command=self._choose_share_folder).grid(
            row=1, column=2, sticky="w", padx=4, pady=4)
        self.share_ftp = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Serve over FTP", variable=self.share_ftp,
                        command=self._share_changed).grid(row=2, column=0, columnspan=3,
                                                          sticky="w", pady=(8, 0))
        ttk.Label(f, text="User:").grid(row=3, column=0, sticky="w", pady=4)
        self.share_user_var = tk.StringVar(value=Share().user)
        self.share_user_entry = ttk.Entry(f, textvariable=self.share_user_var, width=20)
        self.share_user_entry.grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(f, text="Password:").grid(row=4, column=0, sticky="w", pady=4)
        self.share_password_var = tk.StringVar()
        self.share_password_entry = ttk.Entry(f, textvariable=self.share_password_var,
                                              width=20, show="*")
        self.share_password_entry.grid(row=4, column=1, sticky="w", pady=4)
        self.share_scope = tk.StringVar(value="guest-only")
        self.share_scope_rbs = [
            ttk.Radiobutton(f, text="Guest only", variable=self.share_scope, value="guest-only"),
            ttk.Radiobutton(f, text="All interfaces", variable=self.share_scope,
                            value="all-interfaces")]
        self.share_scope_rbs[0].grid(row=5, column=0, columnspan=3, sticky="w")
        self.share_scope_rbs[1].grid(row=6, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="All interfaces needs a password and is for vmnet",
                  foreground=GREY).grid(row=7, column=0, columnspan=3, sticky="w", pady=(2, 0))
        ttk.Label(f, text="In the Mac: ftp://10.0.2.2/ with default (slirp), passive mode",
                  foreground=GREY).grid(row=8, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Use an FTP program such as Fetch or Anarchie",
                  foreground=GREY).grid(row=9, column=0, columnspan=3, sticky="w")

        self.share_volume = tk.BooleanVar(value=False)
        self.share_volume_cb = ttk.Checkbutton(
            f, text="Disk on the Mac's desktop (virtio-9p)", variable=self.share_volume,
            command=self._share_changed)
        self.share_volume_cb.grid(row=10, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Label(f, text="Disk name:").grid(row=11, column=0, sticky="w", pady=4)
        self.share_volume_var = tk.StringVar(value=model.SHARE_DEFAULT_VOLUME)
        self.share_volume_entry = ttk.Entry(f, textvariable=self.share_volume_var, width=20)
        self.share_volume_entry.grid(row=11, column=1, sticky="w", pady=4)
        self.share_volume_note = ttk.Label(f, text="", foreground=GREY,
                                           wraplength=EDITOR_WIDTH - 60, justify="left")
        self.share_volume_note.grid(row=12, column=0, columnspan=3, sticky="w")
        self._share_changed()

    def _share_changed(self):
        ftp = "normal" if self.share_ftp.get() else "disabled"
        for w in (self.share_user_entry, self.share_password_entry, *self.share_scope_rbs):
            w.config(state=ftp)
        t = machine_type(getattr(self, "shown_type", None) or self.machine_id)
        self.share_volume_cb.config(state="normal" if t.host_disk else "disabled")
        on = t.host_disk and self.share_volume.get()
        self.share_volume_entry.config(state="normal" if on else "disabled")
        if not t.host_disk:
            note = f"Not on the {t.label}. Use FTP."
        else:
            note = ("The folder appears in the Finder as a disk, read and write, with "
                    "file types and resource forks. In 24-bit mode it takes about "
                    "0.5 MB of the Mac's memory.")
        self.share_volume_note.config(text=note)

    def _choose_share_folder(self):
        start = paths.browse_start_dir(self.share_folder_var.get(), None)
        d = filedialog.askdirectory(parent=self, initialdir=str(start))
        if d:
            self.share_folder_var.set(d)

    def _build_advanced(self):
        f = self._tab("Advanced")
        f.columnconfigure(0, weight=1)
        self._heading(f, 0, "Additional command line arguments")
        self.extra_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.extra_var, width=70).grid(
            row=1, column=0, sticky="ew")
        ttk.Label(f, text="Added at the end, e.g. -serial stdio",
                  foreground=GREY).grid(row=2, column=0, sticky="w", pady=(4, 0))

    # ---------------- machine type
    def _apply_type_widgets(self, machine_id: str):
        """Memory choices, screens and the EASC box follow the model."""
        t = machine_type(machine_id)
        self.ram_cb.config(values=[str(x) for x in t.ram_choices])
        self.ram_hint.config(text=f"Up to {t.ram_max} MB")
        self.screen_cb.config(values=[s.label for s in t.screens])
        if t.vram_choices:
            self.vram_cb.config(values=[_vram_label(k) for k in t.vram_choices])
            if self.vram_var.get() not in self.vram_cb.cget("values"):
                self.vram_var.set(_vram_label(t.vram_choices[0]))
            self.vram_frame.grid()
        else:
            self.vram_frame.grid_remove()
        self.easc_cb.config(state="normal" if t.easc else "disabled")
        for row in self.floppy_rows:
            row.enable(t.floppy)
        if t.scsi_buses > 1:
            self.ext_scsi.grid()
            self.scsi_heading.config(text=model.scsi_bus_name(0))
        else:
            self.ext_scsi.grid_remove()
            self.scsi_heading.config(text="SCSI")
        self.pds_cb.config(values=systems.pds_labels(machine_id),
                           state="readonly" if t.pds_cards else "disabled")
        self.pds_label.config(text=f"{t.slot_kind} slot:")
        if not t.pds_cards:
            hint = f"The {t.label} has no {t.slot_kind} slot"
        elif t.slot_kind == "NuBus":
            hint = "A card for a NuBus slot (the first one free after the video card)"
        else:
            hint = "Cards for the processor-direct slot"
        self.pds_hint.config(text=hint)
        if systems.pds_by_label(self.pds_var.get()) not in t.pds_cards:
            self.pds_var.set(systems.PDS_EMPTY_LABEL)
        self._update_net_hint()
        if hasattr(self, "share_volume_cb"):
            self._share_changed()

    def _set_pds(self, card_id: str):
        card = systems.pds_card(card_id)
        self.pds_var.set(card.label if card else systems.PDS_EMPTY_LABEL)
        self._update_net_hint()

    def _update_net_hint(self):
        mid = getattr(self, "shown_type", None) or self.machine_id
        t = machine_type(mid)
        if systems.has_nic(mid, systems.pds_by_label(self.pds_var.get())):
            text = "" if t.onboard_nic else f"Ethernet card in the {t.slot_kind} slot"
        elif t.pds_cards:
            text = f"The {t.label} has no Ethernet: put the Ethernet card in its " \
                   f"{t.slot_kind} slot " \
                   "(Machine tab)"
        else:
            text = f"The {t.label} has no Ethernet"
        self.net_hint.config(text=text)

    def _type_chosen(self, _event=None):
        """Switching model carries over what fits (model.apply_machine_type)."""
        new = self.machine_id
        cur = self.collect()
        cur.machine = self.shown_type            # what the fields were filled for
        model.apply_machine_type(cur, new)
        self.shown_type = cur.machine
        self._apply_type_widgets(cur.machine)
        self.rom_var.set(cur.rom)
        self.ram_var.set(str(cur.ram_mb))
        self._set_screen(cur.machine, cur.screen)
        self._set_vram(cur)
        self.icount_var.set(cur.icount)
        self._set_pds(cur.pds)
        self._set_scsi(cur)

    def _set_scsi(self, m: Machine):
        for sid, row in enumerate(self.scsi_rows):
            row.set(m.scsi_by_id(sid))
        for sid, row in enumerate(self.ext_rows):
            row.set(m.scsi_by_id(sid, 1))

    def _set_vram(self, m: Machine):
        kb = model.vram_kb(m)
        self.vram_var.set(_vram_label(kb) if kb else "")

    def _set_screen(self, machine_id: str, screen_id: str):
        s = systems.screen_by_id(machine_id, screen_id) or \
            systems.screen_by_id(machine_id, machine_type(machine_id).screen)
        self.screen_var.set(s.label if s else "")

    # ---------------- load / collect
    def load(self, m: Machine):
        self.name_var.set(m.name)
        self.type_var.set(m.type.label)
        self.shown_type = m.machine
        self._apply_type_widgets(m.machine)
        self._set_pds(m.pds)
        self.ram_var.set(str(m.ram_mb))
        self.rom_var.set(m.rom)
        self.pram_var.set(m.pram)
        self.icount_var.set(m.icount)
        self._set_screen(m.machine, m.screen)
        self._set_vram(m)
        self.display_var.set(m.display)
        self.swap_var.set(m.swap_opt_cmd)
        self.mouse_var.set(_speed_label(m.mouse_speed))
        self._display_changed()
        self._set_scsi(m)
        for i, row in enumerate(self.floppy_rows):
            row.set(m.floppies[i] if i < len(m.floppies) else None)
        self.net_mode_cb.config(
            values=model.network_labels_for_host(paths.HOST_PLATFORM, m.network.mode))
        self.net_mode.set(model.network_mode_label(m.network.mode))
        self.mac_var.set(m.network.mac)
        self.ifname_var.set(m.network.ifname)
        for i, (proto, hp, gp, _w) in enumerate(self.fwd_rows):
            r = m.network.hostfwd[i] if i < len(m.network.hostfwd) else model.HostFwd()
            proto.set(r.proto if r.proto in model.HOSTFWD_PROTOS else "tcp")
            hp.set(r.host_port)
            gp.set(r.guest_port)
        self._net_mode_changed()
        self.audio_var.set(m.audio)
        self.easc_var.set(m.easc)
        self.share_folder_var.set(m.share.folder)
        self.share_user_var.set(m.share.user)
        self.share_password_var.set(m.share.password)
        self.share_scope.set(m.share.scope)
        self.share_ftp.set(m.share.ftp)
        self.share_volume.set(m.share.volume)
        self.share_volume_var.set(m.share.volume_name)
        self._share_changed()
        self.extra_var.set(m.extra_args)

    def collect(self) -> Machine:
        m = self.machine.copy()
        m.name = self.name_var.get().strip()
        m.machine = self.machine_id
        try:
            m.ram_mb = int(self.ram_var.get().strip())
        except ValueError:
            m.ram_mb = -1
        m.rom = self.rom_var.get().strip()
        m.pram = self.pram_var.get().strip()
        m.icount = self.icount_var.get()
        s = systems.screen_by_label(m.machine, self.screen_var.get())
        m.screen = s.id if s else ""
        m.vram_kb = _vram_value(self.vram_var.get()) if m.type.vram_choices else 0
        m.display = self.display_var.get()
        m.swap_opt_cmd = self.swap_var.get()
        m.mouse_speed = _speed_value(self.mouse_var.get(), m.mouse_speed)
        shown = machine_type(getattr(self, "shown_type", None) or m.machine)
        rows = self.scsi_rows + (self.ext_rows if shown.scsi_buses > 1 else [])
        m.scsi = [d for d in (row.get() for row in rows) if d]
        m.floppies = [row.get() for row in self.floppy_rows]
        m.pds = systems.pds_by_label(self.pds_var.get())
        mode = model.network_mode_by_label(self.net_mode.get())
        ifname = self.ifname_var.get().strip() if mode in model.NETWORK_MODES_WITH_IFNAME else ""
        fwd = [model.HostFwd(p.get(), h.get().strip(), g.get().strip())
               for p, h, g, _w in self.fwd_rows]
        m.network = Network(mode, self.mac_var.get().strip(), ifname, fwd)
        m.audio = self.audio_var.get()
        m.easc = self.easc_var.get()
        m.share = Share(self.share_folder_var.get().strip(), self.share_user_var.get().strip(),
                        self.share_password_var.get(), self.share_scope.get(),
                        self.share_ftp.get(), self.share_volume.get(),
                        self.share_volume_var.get().strip() or model.SHARE_DEFAULT_VOLUME)
        m.extra_args = self.extra_var.get().strip()
        return m

    # ---------------- actions
    def _create_disk(self):
        if not self.name_var.get().strip():
            messagebox.showinfo("New hard disk", "Give this machine a name first.",
                                parent=self)
            return
        cur = self.collect()
        dlg = CreateDiskDialog(self, cur, self.machine_folder())
        if not dlg.result:
            return
        path, fmt, sid = dlg.result
        if sid is not None:
            self.scsi_rows[sid].set(ScsiDrive(sid, "disk", path, fmt))
        self.msg.config(text=f"Made {Path(path).name}")

    def save(self):
        m = self.collect()
        errors, warnings = model.validate(m, self.qemu_dir,
                                          machine_dir=str(self.machine_folder()))
        if m.name != self.old_name and self.library.has_record(m.name):
            errors.append(f"You already have a machine called “{m.name}”.")
        self.msg.config(text="  ".join(errors + warnings)[:300])
        if not show_validation(self, errors, warnings):
            return
        try:
            self.on_save(m, self.old_name)
        except (OSError, ValueError) as e:
            messagebox.showerror("Save", str(e), parent=self)
            return
        self.destroy()
