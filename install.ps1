<#
.SYNOPSIS
    Установщик комплекта конвертеров pdf2md / html2md.

.DESCRIPTION
    Делает три вещи:
      1) находит Python (или подсказывает, где скачать);
      2) ставит зависимость markitdown[pdf];
      3) прописывает команды pdf2md / html2md в профиль PowerShell,
         указывая на ту папку, ИЗ КОТОРОЙ запущен этот скрипт.

    Скрипт можно запускать сколько угодно раз — старые строки он
    аккуратно убирает и прописывает заново (идемпотентно).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
#>

$ErrorActionPreference = 'Stop'

# Папка комплекта = там, где лежит этот скрипт (работает после переноса).
$kit = $PSScriptRoot
Write-Host "=== Установка конвертеров PDF/HTML -> Markdown ===" -ForegroundColor Cyan
Write-Host "Папка комплекта: $kit`n"

# --- Проверяем, что рядом лежат сами скрипты ------------------------------
foreach ($f in @('convert_pdf_to_md.py', 'convert_html_to_md.py')) {
    if (-not (Test-Path (Join-Path $kit $f))) {
        Write-Host "Не найден $f рядом с install.ps1. Скопируйте всю папку целиком." -ForegroundColor Red
        exit 1
    }
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
Write-Host "`nУстанавливаю markitdown[pdf] (это может занять минуту)..." -ForegroundColor Cyan
& $python -m pip install --upgrade pip
& $python -m pip install --upgrade "markitdown[pdf]"
& $python -c "import markitdown" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Не удалось установить/импортировать markitdown." -ForegroundColor Red
    Write-Host "Проверьте интернет и попробуйте вручную:" -ForegroundColor Red
    Write-Host "  `"$python`" -m pip install `"markitdown[pdf]`""
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
    if ($line -match '^\s*function\s+(pdf2md|html2md)\b') { continue }
    if ($line -match '^\s*Set-Alias\s+(htmltomd|pdftomd)\b') { continue }
    if ($line -match '^\s*#\s*Конвертер (PDF|HTML) ->') { continue }
    $clean.Add($line)
}

$block = @"
# >>> md-converters >>>
# Конвертеры PDF/HTML -> Markdown. Блок прописан install.ps1 — вручную не редактируйте.
function pdf2md  { & "$python" "$kit\convert_pdf_to_md.py"  @args }
function html2md { & "$python" "$kit\convert_html_to_md.py" @args }
Set-Alias pdftomd  pdf2md
Set-Alias htmltomd html2md
# <<< md-converters <<<
"@

$body = ($clean -join "`r`n").TrimEnd()
$content = if ($body) { "$body`r`n`r`n$block`r`n" } else { "$block`r`n" }
Set-Content -Path $profilePath -Value $content -Encoding utf8BOM

Write-Host "`nКоманды прописаны в профиль:" -ForegroundColor Green
Write-Host "  $profilePath"

# --- 4) Смоук-тест --------------------------------------------------------
$sample = Join-Path $kit 'examples\sample-report.html'
if (Test-Path $sample) {
    Write-Host "`nПроверочная конвертация примера..." -ForegroundColor Cyan
    & $python (Join-Path $kit 'convert_html_to_md.py') $sample --force | Out-Host
}

Write-Host "`n=== Готово! ===" -ForegroundColor Green
Write-Host "Откройте НОВОЕ окно PowerShell (или выполните:  . `$PROFILE )"
Write-Host "и пользуйтесь командами:  pdf2md   и   html2md"
Write-Host "Справка по конвертеру HTML:  html2md --help"
