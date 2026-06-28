# Функциональный контракт Web-GUI (для дизайнера)

Этот файл — «эталон» для редизайна `gui_static/index.html`. Визуал
можно менять как угодно, но **всё перечисленное ниже должно остаться**,
иначе сломается JS-логика. Бренд-стиль — по иконке: градиент
зелёный `#46E0A0` → индиго `#2E2A6E`, мотив «документ + стрелка вниз»
(см. `gui_static/logo.svg`).

## 1. Подключения (НЕ менять, строго same-origin)
```html
<script src="/static/marked.min.js"></script>
<script src="/static/purify.min.js"></script>
```
Никаких внешних CDN/шрифтов: приложение работает офлайн.

## 2. Инлайн `<script>` — оставить БЕЗ изменений
Весь блок логики сохранить как есть (можно переместить в конец body,
но не править). Функции, на которые он опирается:
`loadSettings, save, getFlags, checkSize, addResult, makeBtn, copyPath,
renderRow, convertFiles, convertURL, convertPicked, convertFolderZip,
downloadZip, readStream, flagsToForm, handleSSE, splitFrontMatter,
esc, showPreview, download`.

## 3. id элементов — сохранить ВСЕ (JS обращается по id)
| id | что это |
|----|---------|
| `ver` | `<span>` для версии в шапке |
| `dropZone` | зона drag-and-drop (клик → открывает `fileInput`) |
| `fileInput` | `<input type=file multiple>` (скрытый) |
| `force`, `frontmatter`, `keepImages`, `pdfTables`, `insecureSsl` | чекбоксы настроек |
| `only` | `<select>` форматов |
| `outDir` | `<input type=text>` папки вывода |
| `urlInput` | `<input type=text>` для URL |
| `dirInput` | `<input type=file webkitdirectory multiple>` (скрытый) |
| `results` | контейнер строк-результатов |
| `previewSection` | блок превью (показывается/скрывается) |
| `previewTitle` | заголовок превью |
| `preview` | контейнер, куда рендерится Markdown |

## 4. Обработчики-атрибуты — сохранить
- `onchange="save()"` — на 5 чекбоксах, `#only`, `#outDir`.
- `onclick="convertURL()"` — кнопка URL; `onkeydown` (Enter) на `#urlInput`.
- `onclick="convertPicked('files')"` и `onclick="convertPicked('folder')"`.
- кнопка «Папка → ZIP»: `onclick="document.getElementById('dirInput').click()"`.
- `#dropZone`: слушатели click/dragover/dragleave/drop (в JS) — сохранить
  структуру (клик по зоне = `fileInput.click()`, drop = `convertFiles`).
- атрибуты `multiple`, `webkitdirectory` у инпутов — сохранить.
- `title="…"` (подсказки) — текст можно улучшить, пункты не удалять.

## 5. CSS-классы, которые JS создаёт ДИНАМИЧЕСКИ — обязательно стилизовать
Строки результатов строит `renderRow()`/`addResult()`; без стилей они
будут «голые»:
`result-item`, `cell-name`, `cell-name .status`, `cell-name .name`,
`cell-actions`, `cell-meta`, `cell-path`, `result-note`, `btn`, `btn-sm`.
Превью (`#preview`) — marked рендерит туда Markdown; стилизовать
вложенные: `h1/h2/h3, p, table/th/td, code, pre, blockquote, a, img,
details/summary`.

## 6. Контракт SSE-событий (renderRow/handleSSE это потребляют)
`handleSSE(data)` получает JSON с полем `event` ∈
`start | done | error | zip | cancelled | complete`. Поля:
- `file` — имя/URL (показывается в строке);
- `status` — `ok | skip | fail | pending` (иконка);
- `preview` — текст Markdown для кнопки «Превью»;
- `download_id` — id для кнопки ↓ (`/api/download?dl_id=`);
- `output` — путь сохранённого `.md` (показать «→ путь», клик копирует);
- `error`, `log` — текст ошибки/лога;
- `zip_id`, `count`, `truncated` — для события `zip` (кнопка «Скачать всё»).

## 7. Данные настроек
`getFlags()` читает id из п.3 и шлёт во `FormData` (`flagsToForm`).
`save()`/`loadSettings()` хранят настройки в `localStorage` под ключом
`md-conv-settings`. Имена полей флагов: `force, frontmatter, keep_images,
pdf_tables, insecure_ssl, only, out_dir`.

## 8. Бренд
- Палитра: зелёный `#46E0A0` → синий `#3E5FB0` → индиго `#2E2A6E`
  (диагональ). Тёмный фон `#14152a`/`#1a1a2e`. Кнопки — фиолетовые
  (`#7f7fff`-семейство), зелёный — вторичный/успех.
- Логотип-мотив: `gui_static/logo.svg` (документ + стрелка вниз).
- Шрифт — системный (`-apple-system, system-ui, sans-serif`).
