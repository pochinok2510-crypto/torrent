from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

from core.config import ClientConfig, ConfigManager
from core.engine import TorrentEngine
from core.ipc import SingleInstanceServer
from core.models import TorrentStatusInfo
from core.paths import get_app_dir
from core.state import StateManager
from core.watcher import TorrentWatchFolder
from .dialogs import FileSelectionDialog, SettingsDialog

log = logging.getLogger(__name__)

PRIORITY_LABELS = {
    0: "Не качать",
    1: "Низкий",
    4: "Обычный",
    7: "Высокий",
}


def format_eta(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    if seconds >= 86400:
        return f"{seconds // 86400}д {(seconds % 86400) // 3600}ч"
    if seconds >= 3600:
        return f"{seconds // 3600}ч {(seconds % 3600) // 60}м"
    return f"{seconds // 60}м {seconds % 60}с"


def format_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 Б"
    val = float(num_bytes)
    for unit in ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ"):
        if val < 1024:
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} ПиБ"


def format_rate(bps: int) -> str:
    if bps < 1024:
        return f"{bps} Б/с"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} КиБ/с"
    return f"{bps / (1024 * 1024):.2f} МиБ/с"


class TorrentItemCard(ctk.CTkFrame):
    def __init__(
        self,
        master: tk.Misc,
        info: TorrentStatusInfo,
        selected: bool,
        select: callable,
        toggle: callable,
        open_folder: callable,
        delete_cb: callable,
    ) -> None:
        super().__init__(
            master,
            corner_radius=10,
            border_width=2 if selected else 1,
            border_color="#3b8ed0" if selected else "#3a3f47",
            fg_color="#252a32" if selected else "#1e2229",
        )
        self.info = info
        self.select_cb = select
        self.toggle_cb = toggle
        self.delete_cb = delete_cb
        self.grid_columnconfigure(0, weight=1)

        self.name = ctk.CTkLabel(
            self,
            text=info.name,
            anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.name.grid(row=0, column=0, sticky="ew", padx=12, pady=(9, 2))

        self.meta = ctk.CTkLabel(self, text=self._meta(), anchor="w", text_color="#b8c0cc")
        self.meta.grid(row=1, column=0, sticky="ew", padx=12)

        self.progress = ctk.CTkProgressBar(self)
        self.progress.grid(row=2, column=0, sticky="ew", padx=12, pady=(7, 10))
        self.progress.set(max(0.0, min(1.0, info.progress / 100.0)))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=3, padx=8, pady=6)

        self.select_btn = ctk.CTkButton(
            actions,
            text="Выбрано" if selected else "Выбрать",
            width=82,
            height=26,
            fg_color="#2b6cb0" if selected else ("#3a7ebf", "#1f538d"),
            command=lambda: self.select_cb(self.info.info_hash),
        )
        self.select_btn.pack(pady=2)

        self.toggle_btn = ctk.CTkButton(
            actions,
            text="Старт" if info.paused else "Пауза",
            width=82,
            height=26,
            command=lambda: self.toggle_cb(self.info.info_hash),
        )
        self.toggle_btn.pack(pady=2)

        ctk.CTkButton(
            actions,
            text="Папка",
            width=82,
            height=26,
            fg_color="#323842",
            hover_color="#404854",
            command=lambda: open_folder(self.info.save_path),
        ).pack(pady=2)

        ctk.CTkButton(
            actions,
            text="Удалить",
            width=82,
            height=26,
            fg_color="#7f232e",
            hover_color="#9c2b38",
            command=lambda: self.delete_cb(self.info.info_hash),
        ).pack(pady=2)

        for widget in (self, self.name, self.meta, self.progress):
            widget.bind("<Button-1>", lambda _event, h=info.info_hash: self.select_cb(h))

    def _meta(self) -> str:
        i = self.info
        return (
            f"{i.state} • {i.progress:.1f}%  ↓ {format_rate(i.download_rate)}  "
            f"↑ {format_rate(i.upload_rate)}  •  Пиры: {i.num_peers} (Сиды: {i.num_seeds})  •  "
            f"ETA: {format_eta(i.eta_seconds)}"
        )

    def update_info(self, info: TorrentStatusInfo, selected: bool) -> None:
        self.info = info
        self.name.configure(text=info.name)
        self.meta.configure(text=self._meta())
        self.progress.set(max(0.0, min(1.0, info.progress / 100.0)))
        self.configure(
            border_width=2 if selected else 1,
            border_color="#3b8ed0" if selected else "#3a3f47",
            fg_color="#252a32" if selected else "#1e2229",
        )
        self.select_btn.configure(
            text="Выбрано" if selected else "Выбрать",
            fg_color="#2b6cb0" if selected else ("#3a7ebf", "#1f538d"),
        )
        self.toggle_btn.configure(text="Старт" if info.paused else "Пауза")


class TorrentClientApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("Torrent Desk — личный торрент-клиент")
        self.geometry("1160x780")
        self.minsize(880, 600)

        self._apply_window_icon()
        self.after(200, self._apply_window_icon)

        self.app_dir = get_app_dir()
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()
        Path(self.config.download_dir).mkdir(parents=True, exist_ok=True)
        Path(self.config.watch_dir).mkdir(parents=True, exist_ok=True)

        try:
            self.state_manager = StateManager()
            self.engine = TorrentEngine(self.config, self.state_manager)
        except Exception as exc:
            messagebox.showerror(
                "Ошибка libtorrent",
                f"Не удалось запустить движок. Установи зависимости из requirements.txt.\n\n{exc}",
            )
            raise

        self.selected: str | None = None
        self.cards: dict[str, TorrentItemCard] = {}
        self.tray_icon = None
        self.tray_thread: threading.Thread | None = None

        self._build_ui()
        self.server = SingleInstanceServer(
            lambda values: self.after(0, lambda v=values: self._on_ipc_message(v))
        )
        self.server.start()
        self.watcher = TorrentWatchFolder(self.config.watch_dir, self._watch_add)
        self.watcher.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._tick)

    def _on_ipc_message(self, values: list[str]) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
        self._apply_window_icon()
        if values:
            self.handle_sources(values)

    def _apply_window_icon(self) -> None:
        try:
            base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
            icon_path = base_dir / "VL_icon.ico"
            if icon_path.is_file():
                self.iconbitmap(default=str(icon_path))
                self.wm_iconbitmap(str(icon_path))
        except Exception:
            log.debug("Не удалось применить иконку окна", exc_info=True)

    def _build_ui(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=14, pady=12)

        self.source = ctk.CTkEntry(top, placeholder_text="Вставь magnet-ссылку или путь к .torrent…")
        self.source.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self.source.bind("<Return>", lambda _e: self._add_from_entry())

        ctk.CTkButton(top, text="Вставить", width=82, command=self._paste).pack(side="left", padx=3)
        ctk.CTkButton(top, text="Файл…", width=78, command=self._browse).pack(side="left", padx=3)
        ctk.CTkButton(top, text="Добавить", width=92, command=self._add_from_entry).pack(side="left", padx=3)
        ctk.CTkButton(
            top,
            text="Реанонс",
            width=84,
            fg_color="#2e3540",
            hover_color="#3c4554",
            command=self._reannounce,
        ).pack(side="left", padx=3)
        ctk.CTkButton(top, text="⚙", width=42, command=self._settings).pack(side="left", padx=5)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        self.list_frame = ctk.CTkScrollableFrame(body, label_text="Загрузки")
        self.list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.detail = ctk.CTkTabview(body)
        self.detail.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        self.detail_text: dict[str, ctk.CTkTextbox] = {}
        for tab in ("Общее", "Файлы", "Трекеры", "Пиры"):
            self.detail.add(tab)
            if tab == "Файлы":
                actions_bar = ctk.CTkFrame(self.detail.tab(tab), fg_color="transparent")
                actions_bar.pack(fill="x", padx=4, pady=(4, 2))
                ctk.CTkButton(
                    actions_bar,
                    text="Настроить приоритеты…",
                    height=28,
                    command=self._priorities,
                ).pack(side="left")

            box = ctk.CTkTextbox(self.detail.tab(tab), wrap="word", font=ctk.CTkFont(size=12))
            box.pack(fill="both", expand=True, padx=4, pady=4)
            box.insert("1.0", "Выберите торрент в списке слева для просмотра информации.")
            box.configure(state="disabled")
            self.detail_text[tab] = box

        self.status = ctk.CTkLabel(self, text="Готово", anchor="w", text_color="#b8c0cc")
        self.status.pack(fill="x", padx=18, pady=(0, 8))

    def _set_tab_text(self, tab: str, content: str) -> None:
        box = self.detail_text[tab]
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", content)
        box.configure(state="disabled")

    def _paste(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            messagebox.showwarning("Буфер обмена", "В буфере нет текста")
            return
        if text:
            self.source.delete(0, "end")
            self.source.insert(0, text)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Torrent files", "*.torrent"), ("All files", "*.*")])
        if path:
            self.source.delete(0, "end")
            self.source.insert(0, path)

    def _add_from_entry(self) -> None:
        value = self.source.get().strip()
        if value:
            self.handle_sources([value])

    def _reannounce(self) -> None:
        self.engine.force_reannounce_all()
        self.status.configure(text="Выполнен принудительный анонс трекерам и DHT")

    def handle_sources(self, sources: list[str]) -> None:
        added_any = False
        for raw in sources:
            source = raw.strip().strip('"')
            if not source:
                continue
            if source.lower().startswith("magnet:?"):
                try:
                    key = self.engine.add_magnet(source)
                    self.selected = key
                    self.status.configure(text="Magnet-ссылка добавлена")
                    added_any = True
                except Exception as exc:
                    messagebox.showerror("Добавление magnet", str(exc))
            elif source.lower().endswith(".torrent") or Path(source).is_file():
                self._add_torrent(Path(source))
                added_any = True
        if added_any:
            self.source.delete(0, "end")
            self._tick(schedule_next=False)

    def _watch_add(self, path: Path) -> None:
        try:
            key = self.engine.add_torrent(path)
            self.after(0, lambda k=key, n=path.name: self._on_watch_added_ui(k, n))
        except Exception as exc:
            log.exception("Не удалось добавить торрент из watch-папки: %s", path)
            self.after(0, lambda error=str(exc): self.status.configure(text=f"Ошибка watch-папки: {error}"))

    def _on_watch_added_ui(self, key: str, name: str) -> None:
        if not self.selected:
            self.selected = key
        self.status.configure(text=f"Автоматически добавлен: {name}")

    def _add_torrent(self, path: Path, from_watch: bool = False) -> None:
        try:
            if self.config.ask_file_selection and not from_watch:
                files = self.engine.preview_files(path)
                dialog = FileSelectionDialog(self, files)
                self.wait_window(dialog)
                if dialog.result is None:
                    return
                priorities, save_path = dialog.result
                key = self.engine.add_torrent(path, save_path, priorities)
            else:
                key = self.engine.add_torrent(path)
            self.selected = key
            self.status.configure(text=f"Добавлен: {path.name}")
        except Exception as exc:
            log.exception("Ошибка добавления торрента")
            if not from_watch:
                messagebox.showerror("Добавление торрента", str(exc))

    def _settings(self) -> None:
        dialog = SettingsDialog(self, self.config)
        self.wait_window(dialog)
        if dialog.result:
            try:
                self.config = dialog.result
                self.config_manager.save(self.config)
                self.engine.apply_config(self.config)
                self.watcher.stop()
                self.watcher = TorrentWatchFolder(self.config.watch_dir, self._watch_add)
                self.watcher.start()
                Path(self.config.download_dir).mkdir(parents=True, exist_ok=True)
                self.status.configure(text="Настройки сохранены")
            except Exception as exc:
                messagebox.showerror("Настройки", str(exc))

    def _toggle(self, key: str) -> None:
        try:
            info = self.engine.details(key)
            if info.paused:
                self.engine.resume(key)
            else:
                self.engine.pause(key)
            self._tick(schedule_next=False)
        except Exception as exc:
            messagebox.showerror("Торрент", str(exc))

    def _delete_torrent(self, key: str) -> None:
        delete_files = messagebox.askyesno(
            "Удаление торрента",
            "Удалить также скачанные файлы с диска?",
        )
        try:
            self.engine.delete(key, delete_files=delete_files)
            if self.selected == key:
                self.selected = None
            self._tick(schedule_next=False)
        except Exception as exc:
            messagebox.showerror("Удаление", str(exc))

    def _open_folder(self, path: str) -> None:
        try:
            target = Path(path)
            target.mkdir(parents=True, exist_ok=True)
            if platform.system() == "Windows":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except (OSError, FileNotFoundError) as exc:
            messagebox.showerror("Папка", str(exc))

    def _select(self, key: str) -> None:
        self.selected = key
        self._tick(schedule_next=False)

    def _priorities(self) -> None:
        if not self.selected:
            messagebox.showinfo("Приоритеты", "Сначала выберите торрент в списке.")
            return
        try:
            info = self.engine.details(self.selected)
            if not info.files:
                messagebox.showinfo("Приоритеты", "Список файлов появится после получения метаданных.")
                return
            dialog = FileSelectionDialog(self, info.files, choose_path=False)
            self.wait_window(dialog)
            if dialog.result:
                self.engine.set_file_priorities(self.selected, dialog.result[0])
                self._tick(schedule_next=False)
        except Exception as exc:
            messagebox.showerror("Приоритеты", str(exc))

    def _render_details(self, info: TorrentStatusInfo | None) -> None:
        if info is None:
            empty_msg = "Выберите торрент в списке слева для просмотра информации."
            for tab in ("Общее", "Файлы", "Трекеры", "Пиры"):
                self._set_tab_text(tab, empty_msg)
            return

        general_lines = [
            f"Название: {info.name}",
            f"Info Hash: {info.info_hash}",
            f"Состояние: {info.state}",
            f"Прогресс: {info.progress:.2f}%",
            f"Скорость: ↓ {format_rate(info.download_rate)}  |  ↑ {format_rate(info.upload_rate)}",
            f"Скачано / Отдано: {format_size(info.total_download)} / {format_size(info.total_upload)}",
            f"Сиды: {info.num_seeds}  |  Пиры: {info.num_peers}",
            f"Папка: {info.save_path}",
        ]
        if info.error:
            general_lines.append(f"Ошибка: {info.error}")
        self._set_tab_text("Общее", "\n".join(general_lines))

        if not info.files:
            self._set_tab_text("Файлы", "Список файлов пока недоступен (ожидание метаданных).")
        else:
            file_lines = [
                f"[{PRIORITY_LABELS.get(f.priority, str(f.priority))}] {f.path} — "
                f"{f.progress * 100:.1f}% ({format_size(f.size)})"
                for f in info.files
            ]
            self._set_tab_text("Файлы", "\n".join(file_lines))

        if not info.trackers:
            self._set_tab_text("Трекеры", "Трекеры не заданы или ещё не получены.")
        else:
            tracker_lines = [
                f"[Tier {t.tier}] {t.url} — {t.status}"
                for t in info.trackers
            ]
            self._set_tab_text("Трекеры", "\n".join(tracker_lines))

        if not info.peers:
            self._set_tab_text("Пиры", "Подключённых пиров пока нет (0). Идёт поиск через трекеры, DHT и PEX.")
        else:
            peer_lines = [
                f"{p.ip} | {p.client} | {p.progress:.1f}% | ↓ {format_rate(p.download_rate)} | ↑ {format_rate(p.upload_rate)}"
                for p in info.peers
            ]
            self._set_tab_text("Пиры", "\n".join(peer_lines))

    def _tick(self, schedule_next: bool = True) -> None:
        try:
            self.engine.process_alerts()
            statuses = self.engine.all_statuses()
            active = {s.info_hash: s for s in statuses}

            if self.selected not in active:
                self.selected = statuses[0].info_hash if statuses else None

            for key, card in list(self.cards.items()):
                if key not in active:
                    card.destroy()
                    self.cards.pop(key, None)

            for info in statuses:
                is_sel = info.info_hash == self.selected
                old = self.cards.get(info.info_hash)
                if old is not None and old.winfo_exists():
                    old.update_info(info, selected=is_sel)
                else:
                    card = TorrentItemCard(
                        self.list_frame,
                        info,
                        selected=is_sel,
                        select=self._select,
                        toggle=self._toggle,
                        open_folder=self._open_folder,
                        delete_cb=self._delete_torrent,
                    )
                    card.pack(fill="x", padx=5, pady=4)
                    self.cards[info.info_hash] = card

                if self.config.pause_on_complete and info.progress >= 100 and not info.paused:
                    self.engine.pause(info.info_hash)

            selected_info = active.get(self.selected) if self.selected else None
            self._render_details(selected_info)

            total_dl = sum(s.download_rate for s in statuses)
            total_ul = sum(s.upload_rate for s in statuses)
            self.status.configure(
                text=(
                    f"Торрентов: {len(statuses)}  |  "
                    f"↓ {format_rate(total_dl)}  |  ↑ {format_rate(total_ul)}"
                )
            )
        except Exception:
            log.exception("Ошибка обновления интерфейса")

        if schedule_next:
            self.after(1000, self._tick)

    def _on_close(self) -> None:
        if getattr(self.config, "minimize_to_tray", False) and self._setup_tray():
            self.withdraw()
            return
        self._shutdown()

    def _setup_tray(self) -> bool:
        try:
            import pystray
            from PIL import Image, ImageDraw

            if self.tray_icon:
                return True
            image = Image.new("RGB", (64, 64), (35, 110, 180))
            draw = ImageDraw.Draw(image)
            draw.ellipse((12, 12, 52, 52), fill="white")
            draw.polygon([(22, 20), (44, 32), (22, 44)], fill=(35, 110, 180))
            menu = pystray.Menu(
                pystray.MenuItem("Открыть", lambda _icon, _item: self.after(0, self._on_ipc_message, [])),
                pystray.MenuItem("Выход", lambda _icon, _item: self.after(0, self._shutdown)),
            )
            self.tray_icon = pystray.Icon("TorrentDesk", image, "Torrent Desk", menu)
            self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            self.tray_thread.start()
            return True
        except ImportError:
            self.config.minimize_to_tray = False
            self.status.configure(text="Трей недоступен: установи pystray и pillow")
            return False
        except Exception:
            log.exception("Не удалось создать трей")
            return False

    def _shutdown(self) -> None:
        try:
            if hasattr(self, "watcher") and self.watcher:
                self.watcher.stop()
        except Exception:
            log.exception("Ошибка остановки watcher")
        try:
            if hasattr(self, "server") and self.server:
                self.server.stop()
        except Exception:
            log.exception("Ошибка остановки IPC-сервера")
        try:
            if hasattr(self, "engine") and self.engine:
                self.engine.shutdown()
        except Exception:
            log.exception("Ошибка остановки движка")
        try:
            self.config_manager.save(self.config)
        except Exception:
            log.exception("Ошибка сохранения конфига")
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                log.exception("Ошибка закрытия трея")
        try:
            self.quit()
            self.destroy()
        finally:
            os._exit(0)