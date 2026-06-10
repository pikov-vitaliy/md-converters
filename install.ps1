<#
.SYNOPSIS
    Установщик комплекта конвертеров в Markdown (tomd / pdf2md / html2md).

.DESCRIPTION
    Делает четыре вещи:
      1) находит Python (или подсказывает, где скачать);
      2) ставит зависимость markitdown[all] (PDF, Word, Excel и др.);
      3) прописывает команды tomd / pdf2md / html2md в профиль PowerShell,
         указывая на ту папку, ИЗ КОТОРОЙ запущен этот скрипт;
      4) добавляет пункт «Конвертировать в Markdown» в меню правого клика
         Проводника (Отправить / Send to).

    Скрипт можно запускать сколько угодно раз — старые строки он
    аккуратно убирает и прописывает заново (идемпотентно).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
#>

$ErrorActionPreference = 'Stop'

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

# --- 2) Ставим зависимость ------------------------------------------------
Write-Host "`nУстанавливаю markitdown[all] (это может занять пару минут)..." -ForegroundColor Cyan
& $python -m pip install --upgrade pip
& $python -m pip install --upgrade "markitdown[all]"
& $python -c "import markitdown" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не удалось установить/импортировать markitdown." -ForegroundColor Red
    Write-Host "Проверьте интернет и попробуйте вручную:" -ForegroundColor Red
    Write-Host "  `"$python`" -m pip install `"markitdown[all]`""
    exit 1
}
Write-Host "Зависимость установлена." -ForegroundColor Green

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
    $lnk.Description      = 'Конвертировать выбранные файлы в Markdown'
    $lnk.Save()
    Move-Item -LiteralPath $tmpLnk -Destination $finalLnk -Force
    Write-Host "Пункт «Отправить → Конвертировать в Markdown» добавлен." -ForegroundColor Green
} catch {
    Write-Host "Не удалось добавить пункт в меню (не критично): $_" -ForegroundColor Yellow
}

# --- 5) Смоук-тест --------------------------------------------------------
$sample = Join-Path $kit 'examples\sample-report.html'
if (Test-Path $sample) {
    Write-Host "`nПроверочная конвертация примера..." -ForegroundColor Cyan
    & $python (Join-Path $kit 'convert_to_md.py') $sample --force | Out-Host
}

Write-Host "`n=== Готово! ===" -ForegroundColor Green
Write-Host "Откройте НОВОЕ окно PowerShell (или выполните:  . `$PROFILE )"
Write-Host "Команды:  tomd  (любой формат),  pdf2md,  html2md"
Write-Host "Или в Проводнике: правый клик по файлам → Отправить → Конвертировать в Markdown"
Write-Host "Справка:  tomd --help"
