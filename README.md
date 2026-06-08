# RuTracker TUI 🧲

Python-приложение для синхронизации публичных страниц RuTracker в локальную SQLite-базу и удобной работы с ними из терминального UI.

## Возможности

- 🧵 асинхронный многопоточный по смыслу crawler через `asyncio` + пул HTTP-запросов;
- 🔎 быстрый локальный поиск по названиям и описаниям;
- 🎚️ фильтры по сидам, личам, размеру и наличию magnet-ссылки;
- ⌨️ лёгкий TUI на `prompt_toolkit`: `↑/↓`, `/`, `s`, `o`, `d`, `g`, `c`, `q`;
- 🧲 сбор magnet-ссылок, описания, даты регистрации, списка файлов и размеров;
- 🖼️ ASCII-слепок первой картинки из заголовочного/первого поста без сохранения изображения;
- 💾 локальное хранение в SQLite, чтобы форум был доступен офлайн;
- ✨ TUI без тяжёлого UI-фреймворка: таблица, детали, лог и горячие клавиши.

## Быстрый старт

```powershell
py -m pip install -r requirements.txt
py -m rutracker_tui
```

По умолчанию приложение работает в умном режиме:

- если локальная база пустая — сначала запускает синхронизацию;
- если данные уже есть — сразу открывает TUI;
- если сайт временно отвечает `521/429/5xx` — показывает понятную ошибку и не валится сырым traceback.

## Команды

Синхронизация:

```powershell
py -m rutracker_tui sync --workers 8 --delay 0.7
```

Поиск без TUI:

```powershell
py -m rutracker_tui search "linux iso" --min-seeders 5
```

Сортировка как в RuTracker `name="o"`:

```powershell
py -m rutracker_tui search "linux" -o 10      # по сидам
py -m rutracker_tui search "linux" -o 7 --asc # по размеру вверх
py -m rutracker_tui search "" --category "Аниме"
```

Показать карточку темы:

```powershell
py -m rutracker_tui show 123456 --json
```

Показать файлы раздачи:

```powershell
py -m rutracker_tui files 123456
```

Напечатать magnet:

```powershell
py -m rutracker_tui magnet 123456
```

Список форумов и статистика:

```powershell
py -m rutracker_tui forums --limit 20
py -m rutracker_tui stats --json
```

Диагностика базы и доступности сайта:

```powershell
py -m rutracker_tui doctor
```

## Управление TUI

- `↑/↓` — выбрать раздачу в таблице.
- `/` — поиск, `Enter` применить, `Esc` вернуться к таблице.
- `s` — синхронизация.
- `o` — переключить сортировку: зарегистрирован → название → скачивания → сиды → личи → размер.
- `d` — переключить направление сортировки.
- `g` — переключить крупную категорию: все → Аниме → Сериалы → Книги и журналы → ...
- `c` — сбросить фильтры.
- `q` — выход.

Полная справка:

```powershell
py -m rutracker_tui --help
py -m rutracker_tui search --help
```

## Авторизация

Если RuTracker требует вход для magnet-ссылок, задай переменные окружения:

```powershell
$env:RUTRACKER_USERNAME="login"
$env:RUTRACKER_PASSWORD="password"
py -m rutracker_tui sync
```

Используй приложение только для законных целей, соблюдай правила сайта и ставь разумный `--delay`.
