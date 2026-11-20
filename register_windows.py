from __future__ import annotations
import sys
from pathlib import Path

def register(command: str) -> None:
    if sys.platform != "win32": raise SystemExit("Регистрация ассоциаций доступна только в Windows")
    import winreg
    associations={".torrent":("TorrentDesk.Torrent", "URL:TorrentDesk magnet protocol"),
                  "magnet":("TorrentDesk.Magnet", "URL:magnet protocol")}
    for extension,(prog_id,description) in associations.items():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,fr"Software\Classes\{extension}") as key:
            winreg.SetValueEx(key,"",0,winreg.REG_SZ,prog_id)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,fr"Software\Classes\{prog_id}") as key:
            winreg.SetValueEx(key,"",0,winreg.REG_SZ,description)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,fr"Software\Classes\{prog_id}\shell\open\command") as key:
            winreg.SetValueEx(key,"",0,winreg.REG_SZ,command)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r"Software\Classes\magnet") as key:
        winreg.SetValueEx(key,"URL Protocol",0,winreg.REG_SZ,"")
    print("Ассоциации .torrent и magnet зарегистрированы для текущего пользователя.")

if __name__ == "__main__":
    exe=Path(sys.executable).resolve()
    if getattr(sys,"frozen",False): cmd=f'"{exe}" "%1"'
    else: cmd=f'"{exe}" "{Path(__file__).with_name("main.py")}" "%1"'
    register(cmd)
