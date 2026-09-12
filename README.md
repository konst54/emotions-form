# Карта чувств

Незавершённая интерактивная форма упражнения на воспоминание ситуаций, связанных с чувствами. Ответы хранятся локально в браузере, не на сервере.

**Статус: checkpoint, не готовый релиз.** Начните с [HANDOFF.md](HANDOFF.md), затем [TASK.md](TASK.md).

Приложение — один `index.html` без внешних зависимостей. Для публикации предназначен GitHub Pages. Резервные копии ответов не должны попадать в репозиторий.

## Запуск тестов

```sh
uv venv .venv
uv pip install --python .venv/bin/python playwright
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python -m playwright install chromium webkit
.venv/bin/python tests/test_browser.py
TEST_BROWSER=webkit .venv/bin/python tests/test_browser.py
```

Для Linux могут понадобиться системные зависимости Playwright (`playwright install-deps`). На следующем этапе нужны также проверки через HTTP/HTTPS: текущие тесты открывают `file://`.
