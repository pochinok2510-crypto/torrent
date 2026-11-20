from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from .paths import get_app_dir

log = logging.getLogger(__name__)

class StateManager:
    """Persists libtorrent resume data when save-resume alerts arrive."""
    def __init__(self, app_dir: Path | None = None) -> None:
        self.directory = (app_dir or get_app_dir()) / "data"
        self.directory.mkdir(parents=True, exist_ok=True)

    def resume_path(self, info_hash: str) -> Path:
        safe = "".join(c for c in info_hash.lower() if c in "0123456789abcdef")
        if not safe:
            raise ValueError("Некорректный info hash")
        return self.directory / f"{safe}.fastresume"

    def request_save(self, handle: Any) -> None:
        try:
            handle.save_resume_data()
        except Exception:
            log.exception("Не удалось запросить сохранение resume data")

    def handle_alert(self, alert: Any) -> bool:
        if alert.__class__.__name__ != "save_resume_data_alert":
            return False
        try:
            params = alert.params
            info = params if isinstance(params, dict) else None
            if info is None:
                import libtorrent as lt
                encoded = lt.write_resume_data_buf(params)
                ih = str(params.info_hashes.v1).replace("-", "")
            else:
                import libtorrent as lt
                encoded = lt.write_resume_data_buf(info)
                ih = str(info.get("info-hash", ""))
            self.resume_path(ih).write_bytes(bytes(encoded))
            return True
        except Exception:
            log.exception("Ошибка записи fastresume")
            return False

    def load_all(self) -> list[Any]:
        try:
            import libtorrent as lt
        except ImportError:
            return []
        restored = []
        for path in self.directory.glob("*.fastresume"):
            try:
                restored.append(lt.read_resume_data(path.read_bytes()))
            except (OSError, RuntimeError, ValueError):
                log.exception("Не удалось прочитать %s", path)
        return restored
