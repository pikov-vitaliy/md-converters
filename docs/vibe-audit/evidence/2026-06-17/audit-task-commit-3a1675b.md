# Аудит коммита `3a1675b` — SHA-пиннинг экшенов CI

## Контекст

OpenSSF Scorecard (проверка `Pinned-Dependencies`) и GitHub hardening guide
требуют закреплять сторонние GitHub Actions по **неизменяемому commit-SHA**, а
не по плавающему тегу. Плавающий тег (`@v5`) можно передвинуть на другой
коммит при компрометации экшена — твой CI выполняет этот код с
`GITHUB_TOKEN`, поэтому подмена = кража секретов / порча артефактов / инъекция
кода (реальный прецедент: `tj-actions/changed-files`, март 2025). SHA
контентно-адресуем — его передвинуть нельзя.

Изменение чисто инфраструктурное (только `.github/workflows/ci.yml`), логика
конвертера и тесты не затронуты. Это следующий шаг после бампа экшенов на
Node 24 (коммит `61dec35`).

## Что изменилось

Один коммит, 1 файл, +7/-7 строк: каждый `uses:` переведён с плавающего
мажор-тега на полный 40-символьный commit-SHA с комментарием версии.

| Экшен | Было | Стало (SHA # версия) |
|------|------|----------------------|
| `actions/checkout` (×3) | `@v5` | `@93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5.0.1` |
| `actions/setup-python` (×3) | `@v6` | `@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6.2.0` |
| `actions/upload-artifact` (×1) | `@v6` | `@b7c566a772e6b6bfb58ed0dc250532a479d7789f # v6.0.0` |

## Что НЕ делаем (по решению автора)

- **Пиннинг служебных составных экшенов внутри checkout/setup-python** — не
  наш слой; за их транзитивные зависимости отвечают сами вендоры экшенов.
- **Ручное обновление SHA** — не нужно: Dependabot (`github-actions`,
  еженедельно) ведёт SHA-пины автоматически (бампит и хэш, и комментарий).

## Задание аудитору

### 1. Состав коммита

```powershell
git -C "V:\md-converters" show --stat 3a1675b
# Ожидаемо: 1 файл .github/workflows/ci.yml, +7/-7, больше ничего.

git -C "V:\md-converters" fetch origin
git -C "V:\md-converters" rev-list --left-right --count main...origin/main
# Ожидаемо: "0 0".
```

### 2. Все экшены закреплены по 40-символьному SHA, плавающих тегов нет

```powershell
Select-String -Path "V:\md-converters\.github\workflows\ci.yml" -Pattern "uses:"
# Ожидаемо: каждый uses: вида owner/action@<40 hex> # vX.Y.Z.
# НЕ должно остаться @v5 / @v6 / @v4 (плавающих мажор-тегов).
```

### 3. SHA подлинный: соответствует заявленному тегу версии (ключевая проверка)

Главная цель пиннинга — выполнять именно тот код, что под версией. Аудитор
обязан подтвердить, что каждый запиненный SHA — это коммит, на который
указывает заявленный тег у апстрима (а не произвольный/чужой коммит):

```powershell
# checkout v5.0.1
gh api repos/actions/checkout/commits/v5.0.1 --jq .sha
# Ожидаемо: 93cb6efe18208431cddfb8368fd83d5badbf9bfd

# setup-python v6.2.0
gh api repos/actions/setup-python/commits/v6.2.0 --jq .sha
# Ожидаемо: a309ff8b426b58ec0e2a45f0f869d46889d02405

# upload-artifact v6.0.0
gh api repos/actions/upload-artifact/commits/v6.0.0 --jq .sha
# Ожидаемо: b7c566a772e6b6bfb58ed0dc250532a479d7789f
```

Каждый вывод должен совпасть с SHA в `ci.yml` для соответствующего экшена.

### 4. Зелёный CI без аннотаций (экшены по SHA резолвятся)

```powershell
# Эталонный ран этого коммита: 27653134371
gh run view 27653134371 --repo pikov-vitaliy/md-converters --json status,conclusion
# Ожидаемо: status=completed, conclusion=success.

gh api repos/pikov-vitaliy/md-converters/actions/runs/27653134371/jobs `
  --jq '.jobs[].id' | ForEach-Object {
    gh api "repos/pikov-vitaliy/md-converters/check-runs/$_/annotations" --jq '.[].message'
  }
# Ожидаемо: пусто (0 аннотаций).
```

### 5. Dependabot ведёт SHA-пины

```powershell
Get-Content "V:\md-converters\.github\dependabot.yml"
# Ожидаемо: есть блок package-ecosystem: "github-actions", schedule weekly.
# Dependabot понимает SHA-пины и обновляет и хэш, и # vX.Y.Z комментарий.
```

### 6. Локальное здоровье репозитория не затронуто

Изменение CI-only, но для полноты тот же набор, что и в CI (через `uv`):

```powershell
cd V:\md-converters
uv lock --check
uv sync --frozen
uv run --frozen python -m py_compile convert_to_md.py tools/supply_chain_report.py
uv run --frozen ruff check convert_to_md.py tests tools
uv run --frozen pytest -q
# Ожидаемо: lock ok, ruff "All checks passed!", "56 passed".
```

## Что НЕ проверяет аудитор (и почему)

- **Содержимое кода экшенов по SHA** — доверие к апстриму на момент пиннинга;
  смысл SHA-пина в том, что после фиксации код уже не сменится незаметно.
- **Self-hosted раннеры** — проект использует только GitHub-hosted.

## Критически важные наблюдения

1. **Подлинность SHA важнее факта пиннинга.** Запинить можно и на вредоносный
   SHA — поэтому блок §3 (SHA == коммит заявленного тега) обязателен, иначе
   пиннинг даёт ложное чувство безопасности.
2. **Полные 40 символов.** Короткий SHA небезопасен и не принимается как
   надёжный пин — все три по 40 hex.
3. **Комментарий версии — для людей и Dependabot.** Без `# vX.Y.Z` пин
   нечитаем; Dependabot обновляет и хэш, и комментарий.
4. **Актуальность не теряется** именно благодаря Dependabot — пиннинг без
   автообновления со временем «застывает» на непропатченных версиях.

## Ожидаемый вердикт

✅ Принять — если состав коммита чистый (1 файл, +7/-7), все `uses:`
   закреплены по 40-символьному SHA без плавающих тегов, каждый SHA совпадает
   с коммитом заявленного тега у апстрима (§3), эталонный ран `27653134371`
   зелёный и без аннотаций, Dependabot покрывает `github-actions`.

❌ Отклонить — с указанием, какой SHA не совпал с тегом, остался ли плавающий
   тег или упал ран.
