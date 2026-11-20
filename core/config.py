from __future__ import annotations
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any
from .paths import get_app_dir

@dataclass(slots=True)
class ClientConfig:
    download_dir: str = str(get_app_dir() / "downloads")
    watch_dir: str = str(get_app_dir() / "watch")
    download_limit_kib: int = 0
    upload_limit_kib: int = 0
    listen_port: int = 6881
    enable_dht: bool = True
    enable_lsd: bool = True
    enable_upnp: bool = True
    enable_natpmp: bool = True
    max_active_downloads: int = 5
    max_active_seeds: int = 5
    pause_on_complete: bool = False
    minimize_to_tray: bool = False
    ask_file_selection: bool = True

    def validate(self) -> None:
        for name in ("download_limit_kib", "upload_limit_kib", "max_active_downloads", "max_active_seeds"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name}: значение не может быть отрицательным")
        if not 1 <= self.listen_port <= 65535:
            raise ValueError("Порт должен быть в диапазоне 1..65535")
        if not self.download_dir.strip() or not self.watch_dir.strip():
            raise ValueError("Папки загрузок и наблюдения обязательны")

class ConfigManager:
    def __init__(self, app_dir: Path | None = None) -> None:
        self.path = (app_dir or get_app_dir()) / "data" / "config.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> ClientConfig:
        try:
            raw: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = {f.name for f in fields(ClientConfig)}
            config = ClientConfig(**{k: v for k, v in raw.items() if k in allowed})
            config.validate()
            return config
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return ClientConfig()

    def save(self, config: ClientConfig) -> None:
        config.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
