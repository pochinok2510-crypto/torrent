from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Callable

log = logging.getLogger(__name__)

IPC_HOST = "127.0.0.1"
IPC_PORT = 45819
WAKE_PAYLOAD = b"__TORRENT_DESK_ACTIVATE__\n"


def send_to_running_instance(args: list[str] | None = None) -> bool:
    """Отправляет аргументы (или сигнал активации) уже запущенному экземпляру.
    Возвращает True, если активный экземпляр найден и сигнал доставлен.
    """
    items = [str(x) for x in (args or []) if str(x).strip()]
    message = (
        (json.dumps({"args": items}, ensure_ascii=False) + "\n").encode("utf-8")
        if items
        else WAKE_PAYLOAD
    )
    try:
        with socket.create_connection((IPC_HOST, IPC_PORT), timeout=0.6) as sock:
            sock.settimeout(0.6)
            sock.sendall(message)
            try:
                _ = sock.recv(64)
            except OSError:
                pass
        return True
    except OSError:
        return False


class SingleInstanceServer:
    """Локальный TCP-сервер для приёма команд от повторных запусков приложения."""

    def __init__(self, on_message: Callable[[list[str]], None]) -> None:
        self.on_message = on_message
        self._stop_event = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        try:
            sock.bind((IPC_HOST, IPC_PORT))
            sock.listen(8)
        except OSError:
            log.exception("Не удалось запустить IPC-сервер на %s:%s", IPC_HOST, IPC_PORT)
            sock.close()
            return
        self._sock = sock
        self._thread = threading.Thread(target=self._serve_loop, name="SingleInstanceIPC", daemon=True)
        self._thread.start()

    def _serve_loop(self) -> None:
        while not self._stop_event.is_set() and self._sock is not None:
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(0.5)
                chunks: list[bytes] = []
                while True:
                    try:
                        data = conn.recv(4096)
                    except TimeoutError:
                        break
                    except OSError:
                        break
                    if not data:
                        break
                    chunks.append(data)
                    if b"\n" in data:
                        break
                raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
                values: list[str] = []
                if raw and raw != WAKE_PAYLOAD.decode("utf-8").strip():
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict) and isinstance(parsed.get("args"), list):
                            values = [str(x) for x in parsed["args"] if str(x).strip()]
                    except json.JSONDecodeError:
                        values = [line.strip() for line in raw.splitlines() if line.strip()]
                try:
                    self.on_message(values)
                except Exception:
                    log.exception("Ошибка обработки IPC-сообщения")
                try:
                    conn.sendall(b"OK\n")
                except OSError:
                    pass

    def stop(self) -> None:
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None