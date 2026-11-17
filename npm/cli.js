#!/usr/bin/env node
// md-converters для npm: обёртка над Python-приложением.
//
// Приложение написано на Python 3.14. При первом запуске обёртка готовит
// собственное окружение в папке пользователя (не в node_modules, чтобы оно
// пережило переустановку пакета и не требовало прав администратора):
//   Windows: %LOCALAPPDATA%\md-converters\<версия>\venv
//   Linux/macOS: ~/.local/share/md-converters/<версия>/venv
// Зависимости ставятся строго по uv.lock (requirements.txt с хешами,
// собирается при упаковке), сам пакет — из готового колеса в npm/wheel.
//
// Порядок поиска инструмента установки:
//   1. uv в PATH или ранее поставленный обёрткой uv;
//   2. Python 3.14 в системе — venv + pip;
//   3. официальный установщик uv (astral.sh) в папку обёртки, без правки
//      PATH; uv сам скачает Python 3.14.
//
// Запуск: без аргументов или с «gui» — Web-GUI (откроется браузер);
// иначе аргументы передаются команде tomd.

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const PKG = require('../package.json');
const VERSION = PKG.version;
const HERE = __dirname;
const IS_WIN = process.platform === 'win32';
const PY_MINOR = '3.14';

function dataRoot() {
  if (process.env.MD_CONVERTERS_HOME) return process.env.MD_CONVERTERS_HOME;
  if (IS_WIN) {
    const base = process.env.LOCALAPPDATA ||
      path.join(os.homedir(), 'AppData', 'Local');
    return path.join(base, 'md-converters');
  }
  const base = process.env.XDG_DATA_HOME ||
    path.join(os.homedir(), '.local', 'share');
  return path.join(base, 'md-converters');
}

const ROOT = dataRoot();
const HOME = path.join(ROOT, VERSION);
const VENV = path.join(HOME, 'venv');
const MARK = path.join(HOME, 'installed.json');
const BIN = IS_WIN ? path.join(VENV, 'Scripts') : path.join(VENV, 'bin');
const VPY = path.join(BIN, IS_WIN ? 'python.exe' : 'python');

function say(msg) { process.stderr.write(`[md-converters] ${msg}\n`); }

// Ошибка — исключением, а не process.exit: иначе не выполняется finally,
// и блокировка установки остаётся висеть после обрыва сети.
class UserError extends Error {}

function fail(msg) {
  throw new UserError(msg);
}

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    stdio: opts.quiet ? 'pipe' : 'inherit',
    env: opts.env || process.env,
    windowsHide: true,
    encoding: 'utf8',
  });
  return r;
}

function ok(cmd, args, opts) {
  const r = run(cmd, args, opts);
  return !r.error && r.status === 0 ? r : null;
}

// --- инструменты --------------------------------------------------------

function uvEnv() {
  // Корпоративные сети подменяют сертификаты: uv берёт корни из хранилища
  // системы. Python, который скачивает uv, кладём в папку обёртки.
  const env = Object.assign({}, process.env);
  if (!('UV_NATIVE_TLS' in env)) env.UV_NATIVE_TLS = '1';
  if (!('UV_PYTHON_INSTALL_DIR' in env)) {
    env.UV_PYTHON_INSTALL_DIR = path.join(ROOT, 'python');
  }
  return env;
}

function findUv() {
  const own = path.join(ROOT, 'uv', IS_WIN ? 'uv.exe' : 'uv');
  for (const c of [own, 'uv']) {
    if (ok(c, ['--version'], { quiet: true })) return c;
  }
  return null;
}

function findPython314() {
  const probe = ['-c', 'import sys; print(sys.executable); ' +
    'sys.exit(0 if sys.version_info[:2] == (3, 14) else 1)'];
  const cands = IS_WIN
    ? [['py', ['-3.14']], ['python3.14', []], ['python', []]]
    : [['python3.14', []], ['python3', []], ['python', []]];
  for (const [cmd, pre] of cands) {
    const r = ok(cmd, pre.concat(probe), { quiet: true });
    if (r) return r.stdout.trim().split(/\r?\n/).pop();
  }
  return null;
}

function installUv() {
  say('Ставлю uv (менеджер Python от Astral) в ' +
      path.join(ROOT, 'uv'));
  const env = Object.assign({}, process.env, {
    UV_INSTALL_DIR: path.join(ROOT, 'uv'),
    UV_NO_MODIFY_PATH: '1',
    INSTALLER_NO_MODIFY_PATH: '1',
  });
  // Запуск из PowerShell 7 передаёт его PSModulePath, и Windows PowerShell
  // 5.1 не загружает свои модули (Get-ExecutionPolicy и др.) — установщик
  // падает. Без переменной 5.1 берёт свои пути сам.
  delete env.PSModulePath;
  const r = IS_WIN
    ? run('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass',
      '-Command', 'irm https://astral.sh/uv/install.ps1 | iex'], { env })
    : run('sh', ['-c', 'curl -LsSf https://astral.sh/uv/install.sh | sh'],
      { env });
  if (r.error || r.status !== 0) return null;
  return findUv();
}

// --- установка ----------------------------------------------------------

function wheelPath() {
  const dir = path.join(HERE, 'wheel');
  const w = fs.existsSync(dir)
    ? fs.readdirSync(dir).filter((f) => f.endsWith('.whl')) : [];
  if (w.length !== 1) {
    fail(`В пакете нет колеса Python (${dir}). Переустановите пакет.`);
  }
  return path.join(dir, w[0]);
}

function lock() {
  fs.mkdirSync(HOME, { recursive: true });
  const l = path.join(HOME, '.lock');
  try {
    fs.mkdirSync(l);
  } catch (e) {
    const age = Date.now() - fs.statSync(l).mtimeMs;
    if (age < 30 * 60 * 1000) {
      fail('Установка уже идёт в другом окне. Дождитесь её и запустите ' +
           `снова. Если окна нет — удалите папку ${l}`);
    }
    fs.rmSync(l, { recursive: true, force: true });
    fs.mkdirSync(l);
  }
  return () => fs.rmSync(l, { recursive: true, force: true });
}

function install() {
  const req = path.join(HERE, 'requirements.txt');
  const whl = wheelPath();
  if (!fs.existsSync(req)) fail(`В пакете нет ${req}. Переустановите.`);
  say(`Первый запуск версии ${VERSION}: готовлю Python ${PY_MINOR} и ` +
      'библиотеки (около 400 МБ, несколько минут).');
  say(`Папка: ${HOME}`);
  const unlock = lock();
  try {
    fs.rmSync(VENV, { recursive: true, force: true });
    let uv = findUv();
    const sysPy = uv ? null : findPython314();
    if (!uv && !sysPy) uv = installUv();
    if (uv) {
      const env = uvEnv();
      if (!ok(uv, ['venv', '--python', PY_MINOR, VENV], { env })) {
        fail('uv не смог создать окружение Python 3.14. Проверьте ' +
             'интернет и прокси (HTTPS_PROXY).');
      }
      if (!ok(uv, ['pip', 'install', '--python', VPY, '-r', req],
        { env })) {
        fail('Не удалось поставить библиотеки. Проверьте интернет.');
      }
      if (!ok(uv, ['pip', 'install', '--python', VPY, '--no-deps', whl],
        { env })) {
        fail('Не удалось поставить md-converters.');
      }
    } else if (sysPy) {
      say(`Использую системный Python: ${sysPy}`);
      if (!ok(sysPy, ['-m', 'venv', VENV])) fail('Не создалось окружение.');
      if (!ok(VPY, ['-m', 'pip', 'install', '--disable-pip-version-check',
        '--require-hashes', '-r', req])) {
        fail('Не удалось поставить библиотеки. Проверьте интернет.');
      }
      if (!ok(VPY, ['-m', 'pip', 'install', '--disable-pip-version-check',
        '--no-deps', whl])) {
        fail('Не удалось поставить md-converters.');
      }
    } else {
      fail('Не нашёл Python 3.14 и не смог поставить uv. Поставьте ' +
           'Python 3.14 с https://www.python.org/downloads/ (галочка ' +
           '«Add python.exe to PATH») и запустите снова.');
    }
    if (!ok(VPY, ['-c', 'import convert_to_md, gui_server'],
      { quiet: true })) {
      fail('Окружение собрано, но приложение не импортируется.');
    }
    fs.writeFileSync(MARK, JSON.stringify({
      version: VERSION, at: new Date().toISOString(),
    }));
    cleanupOld();
    say('Готово.');
  } finally {
    unlock();
  }
}

function cleanupOld() {
  // Окружения прежних версий занимают сотни мегабайт: убираем только
  // папки вида «1.2.3» внутри своей папки данных.
  for (const d of fs.readdirSync(ROOT)) {
    if (d !== VERSION && /^\d+\.\d+\.\d+$/.test(d)) {
      try {
        fs.rmSync(path.join(ROOT, d), { recursive: true, force: true });
      } catch (e) { /* занято другим процессом — уберём в следующий раз */ }
    }
  }
}

// --- запуск -------------------------------------------------------------

function main() {
  const args = process.argv.slice(2);
  if (args[0] === '--version' || args[0] === '-V') {
    process.stdout.write(`md-converters ${VERSION} (npm)\n`);
    if (!fs.existsSync(MARK)) return 0;
  }
  if (args[0] === '--where') {
    process.stdout.write(`${HOME}\n`);
    return 0;
  }
  if (args[0] === '--reinstall') {
    fs.rmSync(MARK, { force: true });
    args.shift();
  }
  if (!fs.existsSync(MARK) || !fs.existsSync(VPY)) install();
  const gui = args.length === 0 || args[0] === 'gui';
  const exe = path.join(BIN, (gui ? 'tomd-gui' : 'tomd') +
    (IS_WIN ? '.exe' : ''));
  const r = spawnSync(exe, gui ? args.slice(1) : args, {
    stdio: 'inherit', windowsHide: false,
  });
  if (r.error) fail(`Не запустился ${exe}: ${r.error.message}`);
  return r.status === null ? 1 : r.status;
}

try {
  process.exit(main());
} catch (e) {
  say(e instanceof UserError ? e.message : String(e && e.stack || e));
  process.exit(1);
}
