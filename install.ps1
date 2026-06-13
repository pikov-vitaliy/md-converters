<#
.SYNOPSIS
    Установщик комплекта конвертеров в Markdown (tomd / pdf2md / html2md).

.DESCRIPTION
    Делает пять вещей:
      1) находит Python (или подсказывает, где скачать);
      2) ставит текущий комплект md-converters и его зависимости
         (MarkItDown для PDF, Word, Excel и др.);
      3) прописывает команды tomd / pdf2md / html2md в профиль PowerShell,
         указывая на ту папку, ИЗ КОТОРОЙ запущен этот скрипт;
      4) добавляет пункт «Конвертировать в Markdown» в меню правого клика
         Проводника (Отправить / Send to);
      5) добавляет тот же пункт в основное контекстное меню Проводника
         (видно через «Show more options» в Windows 11 и в классическом
         меню в Windows 10). Запись создаётся в HKCU — без админ-прав.

    Скрипт можно запускать сколько угодно раз — старые строки он
    аккуратно убирает и прописывает заново (идемпотентно).

.PARAMETER SkipContextMenu
    Не регистрировать пункт в основном контекстном меню Проводника
    (только Send to). По умолчанию — оба.

.EXAMPLE
    pwsh -ExecutionPolicy Bypass -File .\install.ps1
.EXAMPLE
    pwsh -ExecutionPolicy Bypass -File .\install.ps1 -SkipContextMenu
#>

[CmdletBinding()]
param(
    [switch]$SkipContextMenu
)

$ErrorActionPreference = 'Stop'

# Без этого в Windows-консоли PowerShell-сообщения на кириллице идут
# в OEM-кодировке и превращаются в «кракозябры». Ставим UTF-8 для текущего
# процесса, чтобы Write-Host ниже читался нормально.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
} catch {}

# Скрипту нужен PowerShell 7.2+: -Encoding utf8BOM/utf8NoBOM и поведение
# stderr нативных команд в 5.1 другие, а профиль 5.1 — вообще другой файл.
if ($PSVersionTable.PSVersion -lt [version]'7.2') {
    Write-Host "Нужен PowerShell 7.2+ (pwsh). Запустите так:" -ForegroundColor Red
    Write-Host "  pwsh -ExecutionPolicy Bypass -File .\install.ps1"
    Write-Host "Если pwsh не установлен: winget install Microsoft.PowerShell"
    exit 1
}

# Папка комплекта = там, где лежит этот скрипт (работает после переноса).
$kit = $PSScriptRoot
Write-Host "=== Установка конвертеров в Markdown ===" -ForegroundColor Cyan
Write-Host "Папка комплекта: $kit`n"

# --- Проверяем, что рядом лежит основной скрипт ---------------------------
if (-not (Test-Path (Join-Path $kit 'convert_to_md.py'))) {
    Write-Host "Не найден convert_to_md.py рядом с install.ps1. Скопируйте всю папку." -ForegroundColor Red
    exit 1
}

# --- 1) Ищем Python -------------------------------------------------------
function Find-Python {
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and $cmd.Source -notmatch 'WindowsApps') {
            return $cmd.Source   # пропускаем заглушку из Microsoft Store
        }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $path = & py -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $path) { return $path.Trim() }
        } catch {}
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python не найден." -ForegroundColor Red
    Write-Host "Скачайте Python 3.10+ с https://www.python.org/downloads/"
    Write-Host "При установке обязательно поставьте галочку 'Add python.exe to PATH',"
    Write-Host "затем запустите install.ps1 ещё раз."
    exit 1
}
Write-Host "Python найден: $python" -ForegroundColor Green
& $python --version

# --- 2) Ставим комплект и зависимости -------------------------------------
# Диапазон MarkItDown закреплен в pyproject.toml; ставим именно локальный
# пакет, чтобы на машине была та же версия md-converters, что и в репозитории.
Write-Host "`nУстанавливаю md-converters из текущей папки..." -ForegroundColor Cyan
& $python -m pip install --upgrade pip
& $python -m pip install --upgrade $kit
& $python -c "import convert_to_md, markitdown" 2>$null
if ($LASTEXITCODE -ne 0) {
    # Системный Python без прав на site-packages — пробуем профиль.
    Write-Host "Не вышло в site-packages, пробую установку с --user..." -ForegroundColor Yellow
    & $python -m pip install --user --upgrade $kit
    & $python -c "import convert_to_md, markitdown" 2>$null
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не удалось установить/импортировать md-converters." -ForegroundColor Red
    Write-Host "Проверьте интернет и попробуйте вручную:" -ForegroundColor Red
    Write-Host "  `"$python`" -m pip install --upgrade `"$kit`""
    exit 1
}
Write-Host "Комплект установлен." -ForegroundColor Green

# --- 3) Прописываем команды в профиль PowerShell --------------------------
$profilePath = $PROFILE
$profileDir  = Split-Path $profilePath
if (-not (Test-Path $profileDir))  { New-Item -ItemType Directory -Force $profileDir | Out-Null }
if (-not (Test-Path $profilePath)) { New-Item -ItemType File $profilePath | Out-Null }

# Убираем прежний блок и любые ранее прописанные строки наших команд.
$old   = @(Get-Content $profilePath -ErrorAction SilentlyContinue)
$clean = New-Object System.Collections.Generic.List[string]
$inBlock = $false
foreach ($line in $old) {
    if ($line -match '#\s*>>> md-converters >>>') { $inBlock = $true;  continue }
    if ($line -match '#\s*<<< md-converters <<<') { $inBlock = $false; continue }
    if ($inBlock) { continue }
    if ($line -match '^\s*function\s+(tomd|pdf2md|html2md)\b') { continue }
    if ($line -match '^\s*Set-Alias\s+(htmltomd|pdftomd)\b') { continue }
    if ($line -match '^\s*#\s*Конвертер(ы)? .*Markdown') { continue }
    $clean.Add($line)
}

$block = @"
# >>> md-converters >>>
# Конвертеры в Markdown (md-converters). Прописано install.ps1 — не редактируйте.
function tomd    { & "$python" "$kit\convert_to_md.py" @args }
function pdf2md  { & "$python" "$kit\convert_to_md.py" --only pdf @args }
function html2md { & "$python" "$kit\convert_to_md.py" --only html,htm @args }
Set-Alias pdftomd  pdf2md
Set-Alias htmltomd html2md
# <<< md-converters <<<
"@

$body = ($clean -join "`r`n").TrimEnd()
$content = if ($body) { "$body`r`n`r`n$block`r`n" } else { "$block`r`n" }
Set-Content -Path $profilePath -Value $content -Encoding utf8BOM

Write-Host "`nКоманды tomd / pdf2md / html2md прописаны в профиль:" -ForegroundColor Green
Write-Host "  $profilePath"

# --- 4) Пункт «Отправить → Конвертировать в Markdown» ---------------------
try {
    $cmdPath = Join-Path $kit 'sendto-convert.cmd'
    $cmdText = @"
@echo off
chcp 65001 >nul
"$python" "$kit\convert_to_md.py" %*
echo.
pause
"@
    Set-Content -Path $cmdPath -Value $cmdText -Encoding utf8NoBOM

    # WScript.Shell теряет кириллицу в ИМЕНИ .lnk (downconvert в ANSI),
    # поэтому создаём по латинскому пути, затем переименовываем (Unicode).
    $sendTo   = Join-Path $env:APPDATA 'Microsoft\Windows\SendTo'
    $tmpLnk   = Join-Path $sendTo '_md_convert_tmp.lnk'
    $finalLnk = Join-Path $sendTo 'Конвертировать в Markdown.lnk'
    if (Test-Path -LiteralPath $finalLnk) { Remove-Item -LiteralPath $finalLnk -Force }
    $ws  = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($tmpLnk)
    $lnk.TargetPath       = $cmdPath
    $lnk.WorkingDirectory = $kit
    # WScript.Shell через COM-маршалинг в PowerShell 7 искажает кириллицу
    # в Description (UTF-16 обрезается). Имя пункта берётся из имени файла
    # .lnk — Description для тултипа не обязателен.
    $lnk.Save()
    Move-Item -LiteralPath $tmpLnk -Destination $finalLnk -Force
    Write-Host "Пункт «Отправить → Конвертировать в Markdown» добавлен." -ForegroundColor Green
} catch {
    Write-Host "Не удалось добавить пункт в Send to (не критично): $_" -ForegroundColor Yellow
}

# --- 4b) Пункт в основном контекстном меню Проводника ---------------------
# HKCU\Software\Classes\*\shell\... — без админ-прав, только для текущего
# пользователя. Position=Middle помогает пункту попасть в видимую часть
# сокращённого меню Windows 11 (иначе он остаётся только в "Show more options").
if (-not $SkipContextMenu) {
    $shellKey = 'Registry::HKEY_CURRENT_USER\Software\Classes\*\shell\ConvertToMarkdown'
    $cmdKey    = "$shellKey\command"
    $menuTitle = 'Конвертировать в Markdown'
    $iconValue = "$python,0"   # иконка из python.exe — есть всегда, не зависит от kit
    $cmdLine   = '"' + $cmdPath + '" "%1"'

    # Симметричное удаление перед переустановкой.
    if (Test-Path -LiteralPath $shellKey) {
        Remove-Item -LiteralPath $shellKey -Recurse -Force
    }

    try {
        New-Item -Path $shellKey -Force | Out-Null
        Set-ItemProperty -LiteralPath $shellKey -Name '(default)' -Value $menuTitle
        Set-ItemProperty -LiteralPath $shellKey -Name 'Icon'      -Value $iconValue
        Set-ItemProperty -LiteralPath $shellKey -Name 'Position'  -Value 'Middle'
        New-Item -Path $cmdKey -Force | Out-Null
        Set-ItemProperty -LiteralPath $cmdKey -Name '(default)' -Value $cmdLine
        Write-Host "Пункт «Конвертировать в Markdown» добавлен в основное контекстное меню Проводника." -ForegroundColor Green
    } catch {
        Write-Host "Не удалось добавить пункт в основное меню (не критично): $_" -ForegroundColor Yellow
    }
}

# --- 5) Смоук-тест --------------------------------------------------------
$sample = Join-Path $kit 'examples\sample-report.html'
if (Test-Path $sample) {
    Write-Host "`nПроверочная конвертация примера..." -ForegroundColor Cyan
    # Без Out-Host: иначе PowerShell забирает stdout Python в свой pipeline
    # и кириллица идёт через его кодировку. С reconfigure() в convert_to_md.py
    # прямой вывод идёт как UTF-8.
    & $python (Join-Path $kit 'convert_to_md.py') $sample --force
}

Write-Host "`n=== Готово! ===" -ForegroundColor Green
Write-Host "Откройте НОВОЕ окно PowerShell (или выполните:  . `$PROFILE )"
Write-Host "Команды:  tomd  (любой формат),  pdf2md,  html2md"
Write-Host "В Проводнике: правый клик → Отправить → Конвертировать в Markdown"
if (-not $SkipContextMenu) {
    Write-Host "  и в основном меню (Show more options) — пункт «Конвертировать в Markdown»."
}
Write-Host "Справка:  tomd --help"
