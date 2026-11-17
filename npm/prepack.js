// Упаковка npm-пакета: колесо Python и requirements.txt с хешами из uv.lock.
// Запускается автоматически перед `npm pack` и `npm publish` (scripts.prepack).
// Нужен uv. Версии package.json и pyproject.toml обязаны совпадать.
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const pkg = require('../package.json');
const pyproject = fs.readFileSync(path.join(ROOT, 'pyproject.toml'), 'utf8');
const m = pyproject.match(/^version\s*=\s*"([^"]+)"/m);
if (!m || m[1] !== pkg.version) {
  console.error(`Версии расходятся: package.json ${pkg.version}, ` +
    `pyproject.toml ${m && m[1]}`);
  process.exit(1);
}

function uv(args) {
  const r = spawnSync('uv', args, { cwd: ROOT, stdio: 'inherit' });
  if (r.error || r.status !== 0) {
    console.error(`uv ${args.join(' ')} — ошибка`);
    process.exit(1);
  }
}

const wheelDir = path.join(__dirname, 'wheel');
fs.rmSync(wheelDir, { recursive: true, force: true });
uv(['lock', '--check']);
uv(['export', '--frozen', '--no-dev', '--extra', 'gui', '--no-emit-project',
  '--no-header', '--format', 'requirements.txt',
  '--output-file', path.join('npm', 'requirements.txt')]);
uv(['build', '--wheel', '--out-dir', path.join('npm', 'wheel')]);
// uv build кладёт в папку вывода .gitignore со «*», а npm его соблюдает.
fs.rmSync(path.join(wheelDir, '.gitignore'), { force: true });
const whl = fs.readdirSync(wheelDir).filter((f) => f.endsWith('.whl'));
if (whl.length !== 1 || !whl[0].includes(`-${pkg.version}-`)) {
  console.error(`Ожидалось одно колесо версии ${pkg.version}: ${whl}`);
  process.exit(1);
}
console.log(`Готово: npm/wheel/${whl[0]}, npm/requirements.txt`);
