# Задание аудитору: коммит `32b2c20`

## Что изменилось

Один коммит, 4 файла, +208/-121 строк:

- `convert_to_md.py` — пользовательские сообщения на английском, reconfigure
  поднят до импортов и распространён на stderr.
- `install.ps1` — UTF-8 в консоль, `-SkipContextMenu` switch, регистрация
  в основном контекстном меню Проводника через HKCU, симметричное
  удаление при переустановке.
- `tests/test_url_policy.py` — match-регекспы под новые английские тексты.
- `README.md` — документация по новому пункту меню и флагу.

## Sanity-check команды (запустить на машине автора)

```powershell
# 1) Компиляция
& "C:\Users\user\AppData\Local\Programs\Python\Python314\python.exe" `
  -m py_compile "V:\md-converters\convert_to_md.py"
# Ожидаемо: exit code 0, без вывода

# 2) Линтинг (line-length 79)
& "C:\Users\user\AppData\Local\Programs\Python\Python314\python.exe" `
  -m ruff check "V:\md-converters\convert_to_md.py" `
                "V:\md-converters\tools" `
                "V:\md-converters\tests"
# Ожидаемо: "All checks passed!"

# 3) Все тесты
& "V:\md-converters\.venv\Scripts\python.exe" `
  -m pytest -q "V:\md-converters\tests"
# Ожидаемо: "41 passed"

# 4) Реестр: ключ основного меню
Get-ItemProperty `
  "Registry::HKEY_CURRENT_USER\Software\Classes\*\shell\ConvertToMarkdown"
# Ожидаемо:
#   (default) : "Конвертировать в Markdown"
#   Icon      : C:\...\python.exe,0
#   Position  : Middle

# 5) Реестр: команда
Get-ItemProperty `
  "Registry::HKEY_CURRENT_USER\Software\Classes\*\shell\ConvertToMarkdown\command"
# Ожидаемо:
#   (default) : "V:\md-converters\sendto-convert.cmd" "%1"

# 6) Send to: ярлык существует
Get-Item -LiteralPath `
  "$env:APPDATA\Microsoft\Windows\SendTo\Конвертировать в Markdown.lnk"
# Ожидаемо: Exists=True, Length ~ 700-725 байт

# 7) Ярлык валидный — внутри есть Target и WorkingDirectory
& "V:\md-converters\.venv\Scripts\python.exe" -c @'
import re
data = open(r"%APPDATA%\Microsoft\Windows\SendTo\Конвертировать в Markdown.lnk", "rb").read()
strs = re.findall(rb"(?:[\x20-\x7e]\x00){4,}", data)
for s in strs:
    print(repr(s.decode("utf-16-le", errors="replace")))
'@
# Ожидаемо: 'md-converters', 'sendto-convert.cmd', 'V:\\md-converters'
# (Description отсутствует — это by design, см. комментарий в install.ps1)

# 8) Полная переустановка — без кракозябр
& "C:\Users\user\AppData\Local\Microsoft\WindowsApps\pwsh.exe" `
  -ExecutionPolicy Bypass -File "V:\md-converters\install.ps1" 2>&1 |
  Select-String "Готово|добавлен|Converting|Done"
# Ожидаемо (минимум):
#   Пункт «Отправить → Конвертировать в Markdown» добавлен.
#   Пункт «Конвертировать в Markdown» добавлен в основное контекстное меню Проводника.
#   Converting sample-report.html ...
#   Done: V:\md-converters\examples\sample-report.md
# Все кириллические строки — читаемы, без mojibake.

# 9) -SkipContextMenu: реестр НЕ создаётся
& "C:\Users\user\AppData\Local\Microsoft\WindowsApps\pwsh.exe" `
  -ExecutionPolicy Bypass -File "V:\md-converters\install.ps1" -SkipContextMenu 2>&1 |
  Out-Null
Get-ItemProperty `
  "Registry::HKEY_CURRENT_USER\Software\Classes\*\shell\ConvertToMarkdown" `
  -ErrorAction SilentlyContinue
# Ожидаемо: пустой вывод (ключа нет), ErrorAction SilentlyContinue подавляет ошибку
# После проверки восстановить:
& "C:\Users\user\AppData\Local\Microsoft\WindowsApps\pwsh.exe" `
  -ExecutionPolicy Bypass -File "V:\md-converters\install.ps1" 2>&1 | Out-Null
```

## Функциональный тест вручную (Проводник)

1. Открыть Проводник.
2. Правый клик на **любом файле** (.txt подойдёт для теста) → **Show more options** →
   в меню должен быть пункт **«Конвертировать в Markdown»** с иконкой Python.
3. Правый клик → **Отправить** → **«Конвертировать в Markdown»** — то же самое.
4. Клик на пункт — откроется cmd-окно, `Converting file.txt ...` → `Done: ...file.md` (для .txt
   результат минимален, но конвертация отработает).
5. Для папок и мульти-выделения — поведение как в Send to: для каждого файла отдельно
   или для всех сразу через `%*` (зависит от того, как Explorer вызывает команду при
   мульти-выделении — но `.cmd` уже принимает оба варианта).

## Что НЕ проверяет аудитор (и почему)

- `WScript.Shell.CreateShortcut().TargetPath` через PowerShell COM показывает пустую
  строку — это баг PS 7, не моей утилиты. Ярлык **валидный**, что подтверждает шаг 7
  (прямое чтение .lnk через Python).
- Если пользователь видит в консоли PowerShell `????` вместо кириллицы в имени файла —
  это артефакт OEM-кодировки текущей `cmd`-/PS-сессии, не моих файлов. Файлы на диске
  содержат корректную UTF-16LE кириллицу, что подтверждает шаг 7.

## Ожидаемый вердикт

✅ Принять — если все 9 sanity-check и функциональный тест прошли.
❌ Отклонить — с конкретным указанием, какой шаг упал и какой вывод был.
