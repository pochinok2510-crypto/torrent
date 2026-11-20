from __future__ import annotations
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from core.config import ClientConfig
from core.models import FileEntry

class FileSelectionDialog(ctk.CTkToplevel):
    def __init__(self, master: tk.Misc, files: list[FileEntry], choose_path: bool = True) -> None:
        super().__init__(master); self.title("Выбор файлов"); self.geometry("680x560"); self.transient(master); self.grab_set()
        self.files = files; self.priorities = [4] * len(files); self.result: tuple[list[int], str | None] | None = None
        self.save_path: str | None = None
        bar = ctk.CTkFrame(self); bar.pack(fill="x", padx=12, pady=10)
        ctk.CTkButton(bar, text="Выбрать все", command=lambda: self._set_all(4)).pack(side="left", padx=5)
        ctk.CTkButton(bar, text="Снять все", command=lambda: self._set_all(0)).pack(side="left", padx=5)
        self.scroll = ctk.CTkScrollableFrame(self); self.scroll.pack(fill="both", expand=True, padx=12, pady=5)
        self.vars: list[tk.IntVar] = []
        for i, entry in enumerate(files):
            row = ctk.CTkFrame(self.scroll); row.pack(fill="x", pady=2)
            var = tk.BooleanVar(value=True); self.vars.append(var)
            ctk.CTkCheckBox(row, text=f"{entry.path}  ({entry.size:,} байт)", variable=var).pack(side="left", padx=8)
            ctk.CTkOptionMenu(row, values=["0", "1", "4", "7"], width=75,
                command=lambda v, idx=i: self._priority(idx, int(v))).pack(side="right", padx=8)
        if choose_path:
            pathrow = ctk.CTkFrame(self); pathrow.pack(fill="x", padx=12, pady=6)
            self.path_label = ctk.CTkLabel(pathrow, text="Папка по умолчанию", anchor="w"); self.path_label.pack(side="left", fill="x", expand=True)
            ctk.CTkButton(pathrow, text="Изменить…", command=self._browse).pack(side="right")
        footer = ctk.CTkFrame(self); footer.pack(fill="x", padx=12, pady=12)
        ctk.CTkButton(footer, text="Добавить", command=self._accept).pack(side="right", padx=5)
        ctk.CTkButton(footer, text="Отмена", fg_color="gray", command=self.destroy).pack(side="right", padx=5)

    def _priority(self, index: int, value: int) -> None:
        self.priorities[index] = value; self.vars[index].set(value != 0)

    def _set_all(self, value: int) -> None:
        self.priorities = [value] * len(self.files)
        for var in self.vars: var.set(value != 0)

    def _browse(self) -> None:
        path = filedialog.askdirectory(parent=self)
        if path: self.save_path = path; self.path_label.configure(text=path)

    def _accept(self) -> None:
        self.priorities = [self.priorities[i] if var.get() else 0 for i, var in enumerate(self.vars)]
        self.result = (self.priorities, self.save_path); self.destroy()

class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master: tk.Misc, config: ClientConfig) -> None:
        super().__init__(master); self.title("Настройки"); self.geometry("560x700"); self.transient(master); self.grab_set()
        self.result: ClientConfig | None = None; self.vars: dict[str, tk.Variable] = {}
        scroll = ctk.CTkScrollableFrame(self); scroll.pack(fill="both", expand=True, padx=12, pady=12)
        specs = [("download_dir", "Папка загрузок", "str"), ("watch_dir", "Watch-папка", "str"),
            ("download_limit_kib", "Лимит скачивания, КиБ/с (0 — без лимита)", "int"),
            ("upload_limit_kib", "Лимит отдачи, КиБ/с (0 — без лимита)", "int"),
            ("listen_port", "Входящий порт (1–65535)", "int"),
            ("max_active_downloads", "Активных загрузок", "int"), ("max_active_seeds", "Активных раздач", "int")]
        for key, label, kind in specs:
            ctk.CTkLabel(scroll, text=label, anchor="w").pack(fill="x", pady=(8, 1))
            var = tk.StringVar(value=str(getattr(config, key))); self.vars[key] = var
            ctk.CTkEntry(scroll, textvariable=var).pack(fill="x")
        bools = [("enable_dht", "DHT"), ("enable_lsd", "Local Peer Discovery (LSD)"), ("enable_upnp", "UPnP"),
            ("enable_natpmp", "NAT-PMP"), ("pause_on_complete", "Ставить на паузу после завершения"),
            ("minimize_to_tray", "Сворачивать в системный трей"), ("ask_file_selection", "Спрашивать выбор файлов при добавлении")]
        for key, label in bools:
            var = tk.BooleanVar(value=getattr(config, key)); self.vars[key] = var
            ctk.CTkCheckBox(scroll, text=label, variable=var).pack(anchor="w", pady=5)
        footer = ctk.CTkFrame(self); footer.pack(fill="x", padx=12, pady=10)
        ctk.CTkButton(footer, text="Сохранить", command=self._save).pack(side="right", padx=5)
        ctk.CTkButton(footer, text="Отмена", fg_color="gray", command=self.destroy).pack(side="right", padx=5)

    def _save(self) -> None:
        try:
            values = {k: v.get() for k, v in self.vars.items()}
            for key in ("download_limit_kib", "upload_limit_kib", "listen_port", "max_active_downloads", "max_active_seeds"):
                values[key] = int(values[key])
            config = ClientConfig(**values); config.validate(); self.result = config; self.destroy()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Некорректные настройки", str(exc), parent=self)
