# БСК слоты — Vercel backend

Парсит свободные окна у Бублика Г. В. с ProDoctorov, отдаёт JSON виджету на bsckrd.ru.

## Структура

```
vercel-app/
├── api/
│   └── slots.py      ← Serverless Function (GET /api/slots)
├── vercel.json       ← конфиг (memory 256 MB, timeout 15 сек)
└── requirements.txt  ← пустой, только stdlib
```

## Деплой за 3 минуты

### Шаг 1 — поставить Vercel CLI

```bash
npm install -g vercel
```

(нужен Node.js. Если нет — `brew install node`)

### Шаг 2 — залогиниться

```bash
cd /Users/urij/Downloads/claude/output/widgets-bsk/vercel-app
vercel login
```

Откроет браузер, выберешь способ (GitHub / email).

### Шаг 3 — задеплоить

```bash
vercel --prod
```

При первом запуске спросит:
- **Set up and deploy?** → Y
- **Which scope?** → твой аккаунт
- **Link to existing project?** → N (новый)
- **Project name?** → `bsk-slots` (или любое)
- **Directory?** → `.` (текущая)
- **Modify settings?** → N

Через 30-60 сек получишь URL вида:
```
https://bsk-slots.vercel.app
```

### Шаг 4 — проверить

```bash
curl "https://bsk-slots.vercel.app/api/slots?doctor=bublik" | python3 -m json.tool | head -40
curl "https://bsk-slots.vercel.app/api/slots?doctor=bublik&date=2026-06-14" | python3 -m json.tool
```

Должен вернуть JSON со свободными слотами.

### Шаг 5 — пришли URL мне

Я обновлю виджет в `doctor-page-bublik.html`:
```js
const API_BASE = "https://bsk-slots.vercel.app/api";
```

## Env-переменные (опционально, в Vercel Dashboard → Settings → Environment Variables)

| Переменная | Значение по умолчанию | Что делает |
|---|---|---|
| `CORS_ORIGIN` | `*` | На проде поставить `https://bsckrd.ru` |
| `DOCTOR_MAPPING_JSON` | (встроен Бублик) | JSON-маппинг slug → {doctor_id, lpu_id, slug, city} |

Пример для добавления Береста, Черонога, Прокопенко:
```json
{
  "bublik": {"doctor_id": 1202028, "lpu_id": 102428, "slug": "1202028-bublik", "city": "krasnodar"},
  "berest": {"doctor_id": 0, "lpu_id": 102428, "slug": "berest-vadim", "city": "krasnodar"},
  "chernonog": {"doctor_id": 0, "lpu_id": 102428, "slug": "chernonog", "city": "krasnodar"},
  "prokopenko": {"doctor_id": 0, "lpu_id": 102428, "slug": "prokopenko", "city": "krasnodar"}
}
```

(Реальные `doctor_id` для остальных нужно вытащить из URL их профилей на ПроДокторов.)

## Риск-факторы

- **IP-блок ProDoctorov:** функции Vercel работают из США/Европы. Если ПроДокторов начнёт блокировать non-RU IP — fetch вернёт ошибку и виджет покажет fallback-кнопку звонка.
- **Изменение API ПроДокторов:** структура `/ajax/schedule/slots_bulk/` может поменяться. Тогда нужно обновить `slots.py`.
- **CSRF rotation:** токен мы берём каждый запрос (5-минутный кэш скрывает накладные расходы).

## Локальный тест

```bash
cd vercel-app
python3 -m http.server 3000  # либо использовать vercel dev
```

Затем:
```bash
vercel dev  # тоже самое, что прод, но локально на 3000
```
