"""The floppy drives of a running machine: put the next disk in, take one
out. Shown in the main window while the selected machine runs; it works
through the machine's control connection (qmp.py), so it does not depend
on the emulator's own window having a menu for it (SDL has none).
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable

from . import model, qmp
from .ui_machine import FLOPPY_TYPES, GREY, ToolTip


class FloppyPanel(ttk.LabelFrame):
    def __init__(self, master, port_of: Callable[[], int | None]):
        super().__init__(master, text="Floppy drives", padding=6)
        self.port_of = port_of
        self.last_dir: str | None = None
        self.files = [tk.StringVar() for _ in range(model.FLOPPY_DRIVES)]
        self.readonly = [tk.BooleanVar(value=False) for _ in range(model.FLOPPY_DRIVES)]
        for i in range(model.FLOPPY_DRIVES):
            ttk.Label(self, text=model.floppy_name(i) + ":").grid(
                row=i, column=0, sticky="w", padx=(0, 6), pady=1)
            ttk.Label(self, textvariable=self.files[i], width=34).grid(
                row=i, column=1, sticky="w", pady=1)
            ro = ttk.Checkbutton(self, text="Read only", variable=self.readonly[i])
            ro.grid(row=i, column=2, sticky="w", padx=6)
            ToolTip(ro, "The next disk goes in locked: the Mac can read it but not "
                        "change it. Use it for install disks.")
            ttk.Button(self, text="Insert…", command=lambda i=i: self.insert(i)).grid(
                row=i, column=3, padx=2, pady=1)
            ttk.Button(self, text="Eject", command=lambda i=i: self.eject(i)).grid(
                row=i, column=4, padx=2, pady=1)
        self.note = ttk.Label(self, foreground=GREY, text=(
            "Drag a disk to the Trash in the Mac first; Insert puts the next one in."))
        self.note.grid(row=model.FLOPPY_DRIVES, column=0, columnspan=5, sticky="w",
                       pady=(4, 0))
        self.columnconfigure(1, weight=1)

    def refresh(self):
        """Show what QEMU has in its drives."""
        port = self.port_of()
        if port is None:
            return
        try:
            files = qmp.floppy_files(port)
        except qmp.QMPError:
            for v in self.files:
                v.set("—")
            self.note.config(text="Waiting for the emulator…")
            return
        for i, v in enumerate(self.files):
            f = files.get(i)
            if i not in files:
                v.set("(no such drive)")
            else:
                v.set(os.path.basename(f) if f else "(empty)")
        self.note.config(text="Drag a disk to the Trash in the Mac first; "
                              "Insert puts the next one in.")

    def insert(self, index: int):
        port = self.port_of()
        if port is None:
            return
        path = filedialog.askopenfilename(
            parent=self, title=f"{model.floppy_name(index)}: the disk to put in",
            filetypes=FLOPPY_TYPES, initialdir=self.last_dir or None)
        if not path:
            return
        self.last_dir = os.path.dirname(path)
        why = model.floppy_problem(path)
        if why:
            messagebox.showerror("Insert", why, parent=self)
            return
        try:
            qmp.insert_floppy(port, index, path, self.readonly[index].get())
        except qmp.QMPError as e:
            messagebox.showerror("Insert", f"The disk could not be put in.\n\n{e}", parent=self)
        self.refresh()

    def eject(self, index: int):
        port = self.port_of()
        if port is None:
            return
        if not messagebox.askyesno(
                "Eject", f"Take the disk out of the {model.floppy_name(index).lower()}? "
                         "If the Mac is using it, eject it in the Mac first (drag it to "
                         "the Trash).", parent=self, icon="warning", default="no"):
            return
        try:
            qmp.eject_floppy(port, index)
        except qmp.QMPError as e:
            messagebox.showerror("Eject", f"The disk could not be taken out.\n\n{e}", parent=self)
        self.refresh()
