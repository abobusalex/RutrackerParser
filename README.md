# RuTracker TUI 🧲

Python-приложение для синхронизации публичных страниц RuTracker в локальную SQLite-базу и удобной работы с ними из терминального UI.

## Возможности

- 🧵 асинхронный многопоточный по смыслу crawler через `asyncio` + пул HTTP-запросов;
- 🔎 быстрый локальный поиск по названиям и описаниям;
- 🎚️ фильтры по сидам, личам, размеру и наличию magnet-ссылки;
- 🧲 сбор magnet-ссылок, описания, даты регистрации, списка файлов и размеров;
- 🖼️ ASCII-слепок первой картинки из заголовочного/первого поста без сохранения изображения;
- 💾 локальное хранение в SQLite, чтобы форум был доступен офлайн;
- ✨ TUI на Textual/Rich с эмодзи, таблицей, логами и быстрыми действиями.

## Быстрый старт

```powershell
py -m pip install -r requirements.txt
py -m rutracker_tui tui
```

Синхронизация:

```powershell
py -m rutracker_tui sync --workers 8 --delay 0.7
```

Поиск без TUI:

```powershell
py -m rutracker_tui search "linux iso" --min-seeders 5
```

## Авторизация

Если RuTracker требует вход для magnet-ссылок, задай переменные окружения:

```powershell
$env:RUTRACKER_USERNAME="login"
$env:RUTRACKER_PASSWORD="password"
py -m rutracker_tui sync
```

Используй приложение только для законных целей, соблюдай правила сайта и ставь разумный `--delay`.
