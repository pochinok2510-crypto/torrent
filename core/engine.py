from __future__ import annotations

import logging
import socket
import time
from pathlib import Path
from typing import Any

from .config import ClientConfig
from .models import FileEntry, PeerEntry, TorrentStatusInfo, TrackerEntry
from .state import StateManager

log = logging.getLogger(__name__)

DHT_BOOTSTRAP_NODES = [
    ("router.bittorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.aelitis.com", 6881),
]

PUBLIC_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.moeking.me:6969/announce",
]


def _format_endpoint(raw_ip: Any) -> str:
    if isinstance(raw_ip, (tuple, list)) and len(raw_ip) >= 2:
        host, port = raw_ip[0], raw_ip[1]
        if ":" in str(host):
            return f"[{host}]:{port}"
        return f"{host}:{port}"
    return str(raw_ip)


class TorrentEngine:
    def __init__(self, config: ClientConfig, state: StateManager) -> None:
        import libtorrent as lt

        self.lt = lt
        self.config = config
        self.state = state
        self.handles: dict[str, Any] = {}
        self._dht_seeded = False

        settings = self._build_settings(config)
        self.session = lt.session(settings)
        self._bootstrap_dht_and_trackers()

        for params in state.load_all():
            try:
                self._ensure_torrent_defaults(params)
                handle = self.session.add_torrent(params)
                key = self._hash(handle)
                self.handles[key] = handle
                self._inject_trackers_if_needed(handle)
            except Exception:
                log.exception("Не удалось восстановить торрент")

    def _build_settings(self, config: ClientConfig) -> dict[str, Any]:
        lt = self.lt
        port = int(getattr(config, "listen_port", 51413) or 51413)
        if port <= 0:
            listen_interfaces = "0.0.0.0:0,[::]:0"
        else:
            listen_interfaces = f"0.0.0.0:{port},[::]:{port}"

        alert_mask = (
            int(lt.alert.category_t.status_notification)
            | int(lt.alert.category_t.error_notification)
            | int(lt.alert.category_t.storage_notification)
            | int(lt.alert.category_t.tracker_notification)
            | int(lt.alert.category_t.dht_notification)
            | int(lt.alert.category_t.peer_notification)
        )

        max_dl = int(getattr(config, "download_limit_kib", 0) or 0) * 1024
        max_ul = int(getattr(config, "upload_limit_kib", 0) or 0) * 1024
        act_dl = max(1, int(getattr(config, "max_active_downloads", 5) or 5))
        act_ul = max(1, int(getattr(config, "max_active_seeds", 5) or 5))

        return {
            "user_agent": "qBittorrent/4.6.7",
            "peer_fingerprint": "-qB4670-",
            "listen_interfaces": listen_interfaces,
            "enable_dht": bool(config.enable_dht),
            "enable_lsd": bool(config.enable_lsd),
            "enable_upnp": bool(config.enable_upnp),
            "enable_natpmp": bool(config.enable_natpmp),
            "download_rate_limit": max(0, max_dl),
            "upload_rate_limit": max(0, max_ul),
            "active_downloads": act_dl,
            "active_seeds": act_ul,
            "active_limit": max(16, act_dl + act_ul + 10),
            "connections_limit": 200,
            "alert_mask": alert_mask,
        }

    def _bootstrap_dht_and_trackers(self) -> None:
        if not self.config.enable_dht:
            self._dht_seeded = False
            return
        if self._dht_seeded:
            return
        for host, port in DHT_BOOTSTRAP_NODES:
            try:
                self.session.add_dht_router(host, port)
            except Exception:
                pass
            try:
                addr_info = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
                for item in addr_info:
                    ip = item[4][0]
                    try:
                        self.session.add_dht_node((ip, port))
                    except Exception:
                        pass
            except OSError:
                continue
        self._dht_seeded = True

    def _ensure_torrent_defaults(self, params: Any) -> None:
        lt = self.lt
        if not getattr(params, "save_path", None):
            params.save_path = self.config.download_dir
        Path(params.save_path).mkdir(parents=True, exist_ok=True)
        params.storage_mode = lt.storage_mode_t.storage_mode_sparse
        try:
            params.flags = (params.flags | lt.torrent_flags.auto_managed) & ~lt.torrent_flags.paused
        except Exception:
            pass

    def _inject_trackers_if_needed(self, handle: Any) -> None:
        try:
            existing = {
                (t.get("url", "") if isinstance(t, dict) else getattr(t, "url", "")).strip()
                for t in handle.trackers()
            }
        except Exception:
            existing = set()

        for url in PUBLIC_TRACKERS:
            if url not in existing:
                try:
                    if hasattr(self.lt, "announce_entry"):
                        handle.add_tracker(self.lt.announce_entry(url))
                    else:
                        handle.add_tracker({"url": url, "tier": 99})
                except Exception:
                    pass

        try:
            handle.force_reannounce()
            if self.config.enable_dht:
                handle.force_dht_announce()
        except Exception:
            pass

    def _hash(self, handle: Any) -> str:
        ih = handle.info_hashes().v1
        return str(ih).replace("-", "").lower()

    def add_magnet(self, magnet: str, save_path: str | None = None) -> str:
        clean = magnet.strip()
        if not clean.lower().startswith("magnet:?"):
            raise ValueError("Некорректная magnet-ссылка")
        params = self.lt.parse_magnet_uri(clean)
        params.save_path = save_path or self.config.download_dir
        self._ensure_torrent_defaults(params)
        handle = self.session.add_torrent(params)
        key = self._hash(handle)
        self.handles[key] = handle
        self._inject_trackers_if_needed(handle)
        return key

    def add_torrent(
        self,
        source: str | Path,
        save_path: str | None = None,
        priorities: list[int] | None = None,
    ) -> str:
        path = Path(source)
        if not path.is_file() or path.suffix.lower() != ".torrent":
            raise ValueError("Выберите существующий .torrent-файл")
        info = self.lt.torrent_info(str(path))
        params = self.lt.add_torrent_params()
        params.ti = info
        params.save_path = save_path or self.config.download_dir
        self._ensure_torrent_defaults(params)
        if priorities is not None:
            params.file_priorities = [int(p) for p in priorities]
        handle = self.session.add_torrent(params)
        key = self._hash(handle)
        self.handles[key] = handle
        self._inject_trackers_if_needed(handle)
        return key

    def preview_files(self, source: str | Path) -> list[FileEntry]:
        info = self.lt.torrent_info(str(source))
        fs = info.files()
        return [
            FileEntry(i, fs.file_path(i), fs.file_size(i))
            for i in range(fs.num_files())
        ]

    def set_file_priorities(self, key: str, priorities: list[int]) -> None:
        handle = self.handles[key]
        ti = handle.torrent_file()
        if ti is None:
            raise ValueError("Метаданные торрента ещё не получены")
        if len(priorities) != ti.files().num_files():
            raise ValueError("Неверное число приоритетов")
        if any(p not in (0, 1, 4, 7) for p in priorities):
            raise ValueError("Допустимые приоритеты: 0, 1, 4, 7")
        handle.prioritize_files([int(p) for p in priorities])

    def pause(self, key: str) -> None:
        handle = self.handles[key]
        try:
            handle.unset_flags(self.lt.torrent_flags.auto_managed)
        except Exception:
            pass
        handle.pause()

    def resume(self, key: str) -> None:
        handle = self.handles[key]
        try:
            handle.set_flags(self.lt.torrent_flags.auto_managed)
        except Exception:
            pass
        handle.resume()
        self._inject_trackers_if_needed(handle)

    def force_reannounce_all(self) -> None:
        self._bootstrap_dht_and_trackers()
        for handle in self.handles.values():
            try:
                handle.force_reannounce()
                if self.config.enable_dht:
                    handle.force_dht_announce()
            except Exception:
                pass

    def apply_config(self, config: ClientConfig) -> None:
        config.validate()
        self.config = config
        Path(self.config.download_dir).mkdir(parents=True, exist_ok=True)
        self.session.apply_settings(self._build_settings(config))
        if config.enable_dht:
            self._bootstrap_dht_and_trackers()
        else:
            self._dht_seeded = False

    def details(self, key: str) -> TorrentStatusInfo:
        h = self.handles[key]
        s = h.status()
        info = h.torrent_file()
        name = s.name or (info.name() if info else f"Торрент {key[:8]}")
        progress = float(s.progress) * 100.0
        eta: int | None = None
        if not bool(s.paused) and s.download_rate > 128:
            remaining = max(0, s.total_wanted - s.total_wanted_done)
            if remaining > 0:
                eta = int(remaining / s.download_rate)

        files: list[FileEntry] = []
        if info:
            fs = info.files()
            priorities = h.get_file_priorities()
            fp = h.file_progress()
            for i in range(fs.num_files()):
                fsize = fs.file_size(i)
                fprog = (float(fp[i]) / fsize) if (i < len(fp) and fsize > 0) else (1.0 if fsize == 0 and s.is_seeding else 0.0)
                fprio = int(priorities[i]) if i < len(priorities) else 4
                files.append(FileEntry(i, fs.file_path(i), fsize, fprog, fprio))

        trackers: list[TrackerEntry] = []
        for idx, t in enumerate(h.trackers()):
            if isinstance(t, dict):
                url = str(t.get("url", ""))
                tier = int(t.get("tier", idx))
                msg = str(t.get("message", "") or "").strip()
                verified = bool(t.get("verified", False))
            else:
                url = str(getattr(t, "url", ""))
                tier = int(getattr(t, "tier", idx))
                msg = str(getattr(t, "message", "") or "").strip()
                verified = bool(getattr(t, "verified", False))
            if not url:
                continue
            status_str = msg if msg else ("OK" if verified else "Ожидание")
            trackers.append(TrackerEntry(url, tier, status_str))

        peers: list[PeerEntry] = []
        for x in h.get_peer_info():
            endpoint = _format_endpoint(getattr(x, "ip", ""))
            client = str(getattr(x, "client", "") or "—")
            prog = float(getattr(x, "progress", 0.0)) * 100.0
            dl_speed = int(getattr(x, "down_speed", 0))
            ul_speed = int(getattr(x, "up_speed", 0))
            peers.append(PeerEntry(endpoint, client, prog, dl_speed, ul_speed))

        state_label = "Пауза" if bool(s.paused) else str(s.state)
        err_msg = str(s.errc.message()) if getattr(s, "errc", None) else ""

        return TorrentStatusInfo(
            key,
            name,
            state_label,
            progress,
            int(s.download_rate),
            int(s.upload_rate),
            int(s.total_download),
            int(s.total_upload),
            int(s.num_seeds),
            int(s.num_peers),
            eta,
            str(h.save_path()),
            bool(s.paused),
            err_msg,
            files,
            trackers,
            peers,
        )

    def all_statuses(self) -> list[TorrentStatusInfo]:
        result: list[TorrentStatusInfo] = []
        for key in list(self.handles):
            try:
                result.append(self.details(key))
            except Exception:
                log.exception("Ошибка получения статуса %s", key)
        return result

    def delete(self, key: str, delete_files: bool = False) -> None:
        handle = self.handles.get(key)
        if handle is None:
            return
        if delete_files:
            save_root = Path(handle.save_path()).resolve()
            ti = handle.torrent_file()
            if ti is not None:
                fs = ti.files()
                touched_dirs: set[Path] = set()
                for index in range(fs.num_files()):
                    candidate = (save_root / fs.file_path(index)).resolve()
                    if candidate == save_root or not candidate.is_relative_to(save_root):
                        log.warning("Пропущен небезопасный путь торрента: %s", candidate)
                        continue
                    touched_dirs.update(candidate.parents)
                    try:
                        if candidate.is_file() or candidate.is_symlink():
                            candidate.unlink(missing_ok=True)
                    except OSError:
                        log.exception("Не удалось удалить файл торрента: %s", candidate)
                for directory in sorted(touched_dirs, key=lambda item: len(item.parts), reverse=True):
                    if directory != save_root and directory.is_relative_to(save_root):
                        try:
                            directory.rmdir()
                        except OSError:
                            continue
        try:
            self.state.request_save(handle)
        except Exception:
            pass
        if delete_files:
            self.session.remove_torrent(handle, self.lt.options_t.delete_files)
        else:
            self.session.remove_torrent(handle)
        self.handles.pop(key, None)

    def process_alerts(self) -> list[Any]:
        alerts = self.session.pop_alerts()
        now = time.monotonic()
        for alert in alerts:
            try:
                self.state.handle_alert(alert)
            except Exception:
                pass
            cls_name = alert.__class__.__name__
            if cls_name == "metadata_received_alert":
                try:
                    log.info("Получены метаданные: %s", alert.handle.name())
                    self._inject_trackers_if_needed(alert.handle)
                except Exception:
                    pass
            elif cls_name == "save_resume_data_alert":
                continue
            elif cls_name in ("tracker_error_alert", "tracker_warning_alert"):
                log.debug("libtorrent tracker (%s): %s", cls_name, alert.message())
            elif "error" in cls_name.lower():
                log.warning("libtorrent: %s", alert.message())

        if self.config.enable_dht and not self._dht_seeded and now > 0:
            self._bootstrap_dht_and_trackers()
        return alerts

    def shutdown(self) -> None:
        expected = len(self.handles)
        saved = 0
        for handle in self.handles.values():
            try:
                self.state.request_save(handle)
            except Exception:
                pass
        try:
            self.session.pause()
            deadline = time.monotonic() + 3.0
            while saved < expected and time.monotonic() < deadline:
                alerts = self.session.pop_alerts()
                if not alerts:
                    time.sleep(0.05)
                    continue
                for alert in alerts:
                    try:
                        if self.state.handle_alert(alert):
                            saved += 1
                    except Exception:
                        pass
        except Exception:
            log.exception("Ошибка при сохранении состояния при выходе")