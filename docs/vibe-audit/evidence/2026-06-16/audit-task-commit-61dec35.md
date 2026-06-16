# Аудит коммита `61dec35` — CI: экшены на Node 24

## Контекст

GitHub выводит из эксплуатации Node.js 20 для JavaScript-экшенов (форс на
Node 24 — с июня 2026, удаление Node 20 с раннеров — 16 сентября 2026).
До этого коммита workflow использовал мажоры на Node 20
(`checkout@v4`, `setup-python@v5`, `upload-artifact@v4`), из-за чего каждый
ран CI помечался deprecation-аннотацией. Изменение — чисто
инфраструктурное (только `.github/workflows/ci.yml`), логика конвертера и
тесты не затронуты.

Сопутствующий контекст той же сессии: 2026-06-16 репозиторий сделан
публичным, чтобы GitHub Actions были бесплатны (на приватном репо исчерпался
платёж за платные минуты и CI спамил «All jobs have failed»). Этот аудит
относится только к бампу экшенов.

## Что изменилось

Один коммит, 1 файл, +7/-7 строк:

| Файл | Что | Назначение |
|------|-----|------------|
| `.github/workflows/ci.yml` | 7 правок `uses:` | `actions/checkout@v4`→`@v5` (×3), `actions/setup-python@v5`→`@v6` (×3), `actions/upload-artifact@v4`→`@v6` (×1) |

Почему именно эти версии:
- **checkout@v5** и **setup-python@v6** — первые мажоры с `runs.using: node24`.
- **upload-artifact@v6** — именно v6, не v5: в v5 поддержка Node 24 была
  предварительной, по умолчанию экшен всё ещё запускался на Node 20; на
  Node 24 по умолчанию переходит только v6.0.0.
- Минимальный раннер для всех трёх — 2.327.1; на GitHub-hosted
  `ubuntu-latest`/`windows-latest` он заведомо новее, так что ограничение
  неактуально.

## Что НЕ делаем (по решению автора)

- **Пиннинг по commit-SHA** вместо плавающих мажор-тегов — не в этом
  коммите. Это отдельное усиление (OpenSSF Scorecard поощряет SHA-пиннинг,
  Dependabot умеет вести и SHA-пины). Оставлено как опциональный следующий
  шаг, чтобы не смешивать с бампом.
- **Опт-ин через `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`** — отвергнут в
  пользу бампа версий: env-var лишь форсит старый код экшена на новом Node,
  а бамп даёт актуальный поддерживаемый код (правильнее для supply-chain).

## Задание аудитору

### 1. Состав коммита

```powershell
git -C "V:\md-converters" show --stat 61dec35
# Ожидаемо: 1 файл .github/workflows/ci.yml, +7/-7, больше ничего.

git -C "V:\md-converters" fetch origin
git -C "V:\md-converters" rev-list --left-right --count main...origin/main
# Ожидаемо: "0 0" (синхронно с origin).
```

### 2. Версии экшенов в workflow

```powershell
Select-String -Path "V:\md-converters\.github\workflows\ci.yml" -Pattern "uses:"
# Ожидаемо ровно:
#   actions/checkout@v5        (3 раза)
#   actions/setup-python@v6    (3 раза)
#   actions/upload-artifact@v6 (1 раз)
# Ни одного @v4 у checkout/upload-artifact и ни одного @v5 у setup-python.
```

### 3. Зелёный CI без deprecation-аннотации (главный критерий)

```powershell
# Эталонный ран этого коммита: 27650814384
gh run view 27650814384 --repo pikov-vitaliy/md-converters --json status,conclusion
# Ожидаемо: status=completed, conclusion=success.

# Аннотации по всем джобам — должно быть ПУСТО (раньше у каждой висела
# "Node.js 20 actions are deprecated ...").
gh api repos/pikov-vitaliy/md-converters/actions/runs/27650814384/jobs `
  --jq '.jobs[].id' | ForEach-Object {
    gh api "repos/pikov-vitaliy/md-converters/check-runs/$_/annotations" --jq '.[].message'
  }
# Ожидаемо: пустой вывод (0 аннотаций).
```

### 4. Локальное здоровье репозитория не затронуто

Бамп — CI-only, но для полноты тот же набор, что гоняет CI (голый `python`
на PATH — заглушка Microsoft Store, поэтому через `uv`):

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

- **Поведение upload-artifact v6 по существу** — джоба `supply-chain`
  выгружает 5 файлов под одним именем; breaking-changes между v4 и v6 для
  такого простого сценария нет (изменился только Node-рантайм). Достаточно
  зелёной джобы `supply-chain` в эталонном ране.
- **Self-hosted раннеры** — проект использует только GitHub-hosted, где
  минимальная версия раннера заведомо удовлетворена.

## Критически важные наблюдения

1. **Не срочно, но правильно.** Сама аннотация исчезла бы и без бампа —
   GitHub всё равно форсит Node 24 на старые экшены. Ценность бампа в том,
   что запускается актуальный поддерживаемый код экшена, а не старый под
   новым рантаймом. Для репозитория с SBOM/SCA это и есть смысл.
2. **upload-artifact: только v6.** Самая частая ошибка — взять v5 и
   остаться на Node 20 по умолчанию. Здесь взят v6 осознанно.
3. **Плавающие мажор-теги сохранены** — соответствует текущему стилю
   workflow. SHA-пиннинг вынесен в отдельный опциональный шаг.

## Ожидаемый вердикт

✅ Принять — если состав коммита чистый (1 файл, +7/-7), версии экшенов
   ровно `@v5/@v6/@v6`, эталонный ран `27650814384` зелёный и без
   аннотаций, локальный набор проверок проходит (56 passed).

❌ Отклонить — с указанием, какой шаг упал и какой был вывод (например,
   если у upload-artifact осталась `@v5` и снова появилась аннотация
   Node 20).
