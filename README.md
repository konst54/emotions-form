# Карта чувств

Незавершённая интерактивная форма упражнения на воспоминание ситуаций, связанных с чувствами. Ответы хранятся локально в браузере, не на сервере.

**Статус: опубликовано.** Рабочая ссылка: https://konst54.github.io/emotions-form/ (GitHub Pages, branch main, корень). История разработки — в [HANDOFF.md](HANDOFF.md), требования — в [TASK.md](TASK.md).

Приложение — один `index.html` без внешних зависимостей. Для публикации предназначен GitHub Pages. Резервные копии ответов не должны попадать в репозиторий.

## Запуск тестов

```sh
uv venv .venv
uv pip install --python .venv/bin/python playwright
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python -m playwright install chromium webkit
.venv/bin/python tests/test_browser.py
TEST_BROWSER=webkit .venv/bin/python tests/test_browser.py
```

Для Linux могут понадобиться системные зависимости Playwright (`playwright install-deps`). Если root недоступен, извлеките их локально без установки:

```sh
.venv/bin/python tests/local_webkit_deps.py
```

Скрипт скачивает deb-пакеты из списка `playwright install-deps --dry-run webkit`, распаковывает их в `.webkit-deps/` и сохраняет наследуемый `LD_LIBRARY_PATH` в обёртке MiniBrowser. Затем прогоните всю матрицу (Chromium и WebKit, `file://` и временный локальный HTTP-сервер):

```sh
.venv/bin/python tests/run_matrix.py
```

Отдельный прогон через HTTP без матрицы: `TEST_BASE_URL=http://127.0.0.1:8000/index.html .venv/bin/python tests/test_browser.py` при запущенном локальном сервере. Логи и скриншоты каждого прогона сохраняются в `test-results/<browser>-<protocol>-final.txt` и `test-results/<browser>-<protocol>/`.
