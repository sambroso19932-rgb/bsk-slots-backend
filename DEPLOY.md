# Деплой за 3-5 минут

У тебя есть `git` и `python3`. Нет Node.js, поэтому два пути.

---

## Путь A — через GitHub + Vercel Web UI (без терминала, рекомендую)

### A1. Создать GitHub-репо

1. Открой https://github.com/new
2. Repository name: `bsk-slots-backend` (любое)
3. Public или Private — пофиг
4. **Не ставить** галочки Initialize with README / .gitignore
5. Жми **Create repository**

GitHub покажет команды для push existing repo. Скопируй блок «...or push an existing repository from the command line».

### A2. Запушить код

Открой терминал, вставь команды (взяв из шага A1 URL своего репо):

```bash
cd /Users/urij/Downloads/claude/output/widgets-bsk/vercel-app
git init
git add .
git commit -m "initial backend"
git branch -M main
git remote add origin https://github.com/<USERNAME>/bsk-slots-backend.git
git push -u origin main
```

При push GitHub спросит логин/пароль — нужен **Personal Access Token** (не пароль):
https://github.com/settings/tokens → Generate new token (classic) → scope `repo` → Generate → скопировать → использовать как пароль.

### A3. Импортировать в Vercel

1. Зарегистрируйся / залогинься: https://vercel.com (выбери Continue with GitHub)
2. На дашборде: **Add New… → Project**
3. Найди `bsk-slots-backend` → **Import**
4. **Framework Preset:** Other
5. **Root Directory:** оставить `.`
6. Нажать **Deploy**

Через 30-60 секунд деплой завершится. URL вида:
```
https://bsk-slots-backend-<хеш>.vercel.app
```

### A4. Проверить

В браузере открой:
```
https://bsk-slots-backend-<хеш>.vercel.app/api/slots?doctor=bublik
```

Должен вернуть JSON со свободными слотами.

### A5. Прислать URL мне

Я обновлю `doctor-page-bublik.html` — впишу URL вместо `YOUR_BACKEND_URL`.

---

## Путь B — через Vercel CLI (если хочешь ставить Node)

### B1. Поставить Node.js

Открой https://nodejs.org/ru → скачай LTS-pkg → запусти. 2 клика, готово.

### B2. Поставить и задеплоить

```bash
npm install -g vercel
cd /Users/urij/Downloads/claude/output/widgets-bsk/vercel-app
vercel login         # выберешь Continue with GitHub
vercel --prod        # ответы по умолчанию (Y / N / project name / .)
```

Через 30 сек CLI напечатает URL. Скопируй и пришли мне.

---

## Что дальше

После деплоя я:
1. Заменю `YOUR_BACKEND_URL` на твой URL в коде виджета на странице Бублика
2. Также для CORS — пропишу `CORS_ORIGIN=https://bsckrd.ru` в Vercel Dashboard (Project Settings → Environment Variables)
3. Прогоним end-to-end: открыли страницу в Tilda → виджет дёргает Vercel → Vercel дёргает ProDoctorov → слоты в гриде

## Возможные риски на проде

- **IP-блок ProDoctorov.** Vercel хостит в США/Европе. ПроДокторов может вернуть 403/captcha с не-RU IP. Тогда виджет покажет fallback-кнопку «Позвонить». Решается переездом на YC или прокси в РФ.
- **Cold start.** Vercel Python функции просыпаются 1-2 сек после простоя. Кэш 5 минут сглаживает.
- **Limits бесплатного тарифа.** 100 GB трафика/мес, 100k запросов/день. Для одной страницы врача — с запасом.
