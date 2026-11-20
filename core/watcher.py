from __future__ import annotations
import logging, shutil, threading, time
from pathlib import Path
from collections.abc import Callable

log = logging.getLogger(__name__)

class TorrentWatchFolder:
    def __init__(self, watch_dir: str | Path, callback: Callable[[Path], None], interval: float = 1.0) -> None:
        self.directory = Path(watch_dir)
        self.processed = self.directory / "processed"
        self.callback = callback
        self.interval = max(0.5, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: dict[Path, tuple[int, float]] = {}

    def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.processed.mkdir(parents=True, exist_ok=True)
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="TorrentWatchFolder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            now = time.monotonic()
            try:
                candidates = list(self.directory.glob("*.torrent"))
            except OSError:
                log.exception("Не удалось прочитать watch-папку")
                continue
            for path in candidates:
                try:
                    size = path.stat().st_size
                    previous = self._seen.get(path)
                    if previous and previous[0] == size and now - previous[1] >= 1.5:
                        try:
                            self.callback(path)
                            self._archive(path)
                        except Exception:
                            log.exception("Ошибка обработки %s", path)
                            self._seen.pop(path, None)
                    else:
                        self._seen[path] = (size, now if not previous or previous[0] != size else previous[1])
                except OSError:
                    self._seen.pop(path, None)
            self._seen = {p: v for p, v in self._seen.items() if p.exists()}

    def _archive(self, path: Path) -> None:
        self.processed.mkdir(parents=True, exist_ok=True)
        target = self.processed / path.name
        if target.exists():
            target = target.with_name(f"{target.stem}_{time.strftime('%Y%m%d_%H%M%S')}{target.suffix}")
        shutil.move(str(path), str(target))
        self._seen.pop(path, None)
