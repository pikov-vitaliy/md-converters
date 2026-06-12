---
title: "Пример отчёта об уязвимостях — demo-project"
source: "sample-report.html"
source_name: "sample-report.html"
source_path: "V:\\md-converters\\examples\\sample-report.html"
source_id: "path:25f57f6cd29e0a1dd29644abe58ec89c"
converted: 2026-06-13
generator: tomd 1.1.0 (MarkItDown)
---

# Отчёт об уязвимостях — demo-project

Сформирован: 2026-06-10

Источник: npm-audit

## Сводка

* Всего находок: 3
* Критических: 1
* Высоких: 0
* Средних: 2

## Находки

| Пакет | Уровень | Описание | Исправление |
| --- | --- | --- | --- |
| left-pad | критический | Удалённое выполнение кода | обновить до 1.3.0 |
| lodash | средний | Загрязнение прототипа | обновить до 4.17.21 |
| minimist | средний | Загрязнение прототипа | обновить до 1.2.6 |

## Рекомендации

Выполните `npm audit fix` и пересоберите проект.
