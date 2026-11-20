from __future__ import annotations

import logging
import sys
from pathlib import Path

from core.ipc import send_to_running_instance


def _resolve_icon_path() -> Path:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_dir / "VL_icon.ico"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if send_to_running_instance(sys.argv[1:]):
        return 0

    from ui.app import TorrentClientApp

    app = TorrentClientApp()
    icon_path = _resolve_icon_path()
    if icon_path.is_file():
        try:
            app.iconbitmap(default=str(icon_path))
            app.wm_iconbitmap(str(icon_path))
        except Exception:
            logging.getLogger(__name__).debug("Не удалось задать иконку в main.py", exc_info=True)

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())