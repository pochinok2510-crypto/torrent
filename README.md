# Torrent Desk

Личный десктопный BitTorrent-клиент на Python, CustomTkinter и libtorrent. Без рекламы и сторонних аккаунтов.

## Установка и запуск

Требуется Python 3.10+ и системные библиотеки, необходимые сборке `libtorrent` для вашей ОС. В Windows рекомендуется установить готовый wheel `libtorrent` для используемой версии Python.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

При первом запуске создаются `downloads/`, `watch/` и `data/`. Помести `.torrent` в `watch/` — после стабилизации размера файл будет добавлен и перемещён в `watch/processed/`. Magnet-ссылки и `.torrent` также можно передать аргументом командной строки; второй запуск передаст их уже открытому окну.

## Сборка

```bash
pyinstaller --onefile --windowed --collect-all customtkinter main.py
```

Для распространения проверьте, что бинарный модуль `libtorrent` и его зависимости включены в сборку; в зависимости от платформы потребуется добавить соответствующие `--collect-binaries`/`--add-binary` параметры. Каталог рядом с exe должен быть доступен для записи.

## Ассоциации файлов

- Windows: запусти `python register_windows.py` из каталога проекта (или `register_windows.exe` после сборки). Скрипт регистрирует `.torrent` и протокол `magnet:` в `HKEY_CURRENT_USER\Software\Classes`.
- Linux: настройте MIME-ассоциацию `application/x-bittorrent` на исполняемый файл через настройки рабочего стола; для `magnet:` зарегистрируйте схему в desktop-файле приложения.
- macOS: назначьте приложение для `.torrent` через Launch Services; обработка URL-схемы `magnet:` требует регистрации URL Types в bundle.

## Данные и безопасность

Настройки хранятся в `data/config.json`, resume-данные — в `data/*.fastresume`. Эти файлы и загрузки исключены из Git. Опция удаления данных предназначена для удаления только верхнего каталога конкретного торрента внутри его папки сохранения.

> Используйте клиент только для загрузки и распространения материалов, на которые у вас есть права.
