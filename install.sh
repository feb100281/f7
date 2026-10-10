#!/usr/bin/env bash
# ============================================================
#  FORMULA7 · Хелпер отдела продаж запчастей — установка проекта
#
#  Положить install.sh в любую папку (например ~/prj) и запустить:
#      bash install.sh            → клонирует репо в ./f7 и ставит
#      bash install.sh mydir      → то же, в ./mydir
#  Если скрипт запущен прямо в папке проекта — просто git pull и установка.
#
#  Работает на macOS (Homebrew) и Linux-сервере (Ubuntu/Debian).
#  База SQLite (db.sqlite3 в папке проекта). Повторный запуск безопасен: обновляет код,
#  зависимости и миграции, ничего не затирает (.env, база, пользователи остаются).
# ============================================================
set -e

REPO="https://github.com/feb100281/f7.git"
DIR="${1:-f7}"

cd "$(dirname "$0")"

if [ -f manage.py ]; then
    echo "— Уже в папке проекта, обновляю: git pull"
    git pull --ff-only 2>/dev/null || echo "  (git pull не получился — ставлю как есть)"
elif [ -d "$DIR/.git" ]; then
    echo "— Репозиторий уже есть в ./$DIR, обновляю: git pull"
    cd "$DIR"
    git pull --ff-only || echo "  (git pull не получился — ставлю как есть)"
else
    echo "— Клонирую $REPO → ./$DIR"
    git clone "$REPO" "$DIR"
    cd "$DIR"
fi

echo "========================================"
echo " FORMULA7 · Запчасти — установка проекта"
echo "========================================"

echo
echo "— Python 3.12"
if ! command -v python3.12 >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
        echo "  python3.12 не найден — ставлю через Homebrew"
        brew install python@3.12
    elif command -v apt-get >/dev/null 2>&1; then
        echo "  ОШИБКА: python3.12 не найден. На сервере (Ubuntu/Debian) поставьте и запустите скрипт снова:"
        echo "      sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3.12-dev"
        echo "  (на Ubuntu 22.04 сначала: sudo add-apt-repository ppa:deadsnakes/ppa)"
        exit 1
    else
        echo "  ОШИБКА: нужен python3.12 (brew install python@3.12 или https://www.python.org)"
        exit 1
    fi
fi
if ! python3.12 -c "import venv, ensurepip" >/dev/null 2>&1; then
    echo "  ОШИБКА: нет модуля venv. Ubuntu/Debian: sudo apt-get install -y python3.12-venv"
    exit 1
fi
python3.12 --version

echo
echo "— Виртуальное окружение (python 3.12)"
if [ -x .venv/bin/python ] && .venv/bin/python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"; then
    echo "  .venv уже есть"
else
    rm -rf .venv
    python3.12 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip

echo
echo "— Зависимости (все версии закреплены в requirements.txt)"
pip install -r requirements.txt

echo
echo "— Проверка зависимостей"
python - <<'PY'
import importlib
mods = ["django", "unfold", "django_json_widget", "dotenv", "duckdb", "pandas", "numpy", "pyarrow",
        "openpyxl", "prophet", "cmdstanpy", "holidays", "gunicorn"]
bad = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as exc:  # noqa: BLE001
        bad.append(f"{m}: {exc}")
if bad:
    print("  НЕ ИМПОРТИРУЮТСЯ:\n    " + "\n    ".join(bad))
    raise SystemExit(1)
print(f"  ок: {len(mods)} пакетов")
PY

echo
echo "— DuckDB: расширение sqlite (скачивается один раз, нужен интернет)"
python -c "import duckdb; c = duckdb.connect(); c.execute('INSTALL sqlite'); c.execute('LOAD sqlite'); print('  ок')"

echo
echo "— Prophet: пробная модель"
python - <<'PY'
import logging, warnings
warnings.filterwarnings("ignore")
for name in ("cmdstanpy", "prophet"):
    logging.getLogger(name).setLevel(logging.ERROR)
import pandas as pd
from prophet import Prophet
df = pd.DataFrame({"ds": pd.date_range("2024-01-01", periods=120, freq="D")})
df["y"] = range(len(df))
Prophet(uncertainty_samples=0).fit(df).predict(df.tail(3))
print("  ок")
PY

echo
echo "— Node.js и Tailwind (стили админки, см. TAILWIND.md)"
if ! command -v npm >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
        echo "  Node не найден — ставлю через Homebrew"
        brew install node
    else
        echo "  ВНИМАНИЕ: Node не найден и нет Homebrew."
        echo "  Поставьте Node.js LTS с https://nodejs.org и выполните в папке проекта: npm install"
        echo "  (проект запустится и без Node — он нужен только для правки стилей)"
    fi
fi
if command -v npm >/dev/null 2>&1; then
    if [ -f package-lock.json ]; then npm ci || npm install; else npm install; fi
    npm run css:build || echo "  (сборка стилей не получилась — используется готовый output.css)"
fi

echo
if [ -f .env ]; then
    echo "— .env уже есть, не трогаю"
else
    echo "— Создаю .env (SQLite, DEBUG, новый SECRET_KEY)"
    SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
    cat > .env << ENV
SECRET_KEY='${SECRET}'
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
# На сервере: DEBUG=False, свой домен в ALLOWED_HOSTS и CSRF_TRUSTED_ORIGINS=https://домен
CSRF_TRUSTED_ORIGINS=
ENV
fi

echo
echo "— Миграции"
python manage.py migrate

echo
echo "— Статика (для gunicorn / nginx на сервере)"
python manage.py collectstatic --noinput -v 0 && echo "  ок: staticfiles/"

echo
echo "— Начальные данные: группы, список команд (sync_jobs), товарные группы"
python manage.py firstrun

echo
echo "— Суперпользователь"
if python manage.py shell -c "from django.contrib.auth import get_user_model as g; import sys; sys.exit(0 if g().objects.filter(is_superuser=True).exists() else 1)"; then
    echo "  суперпользователь уже есть, пропускаю"
else
    python manage.py createsuperuser
fi

echo
echo "— Данные продаж"
SRC=$(python manage.py shell -v 0 -c "from core.models import Jobs; j = Jobs.objects.filter(command='parse_sales').first(); print((j.param or {}).get('source', '') if j else '')")
SRC_DIR="${SRC/#\~/$HOME}"
if python manage.py shell -v 0 -c "import sys; from sales.models import SalesLine; sys.exit(0 if SalesLine.objects.exists() else 1)"; then
    echo "  продажи уже в базе — пересчитываю витрины (SQL мог обновиться)"
    python manage.py build_marts || echo "  (витрины не пересчитались — см. ошибку выше)"
elif [ -n "$SRC" ] && [ -d "$SRC_DIR" ]; then
    read -r -p "  Загрузить продажи из $SRC сейчас? [Y/n] " ANSWER
    if [[ ! "$ANSWER" =~ ^[NnНн] ]]; then
        python manage.py parse_sales || echo "  (импорт не получился — см. ошибку выше)"
    else
        echo "  пропускаю — потом: админка → Система → Команды → «Импорт продаж из 1С»"
    fi
else
    echo "  папка с выгрузками не найдена: ${SRC:-не задана}"
    echo "  локально — укажите source в админке → Система → Команды → «Импорт продаж из 1С» и запустите её;"
    echo "  на сервере — данные придут с локальной машины командой «Опубликовать»"
fi

echo
echo "========================================"
echo " Готово. Запуск локально:"
echo "   cd $(pwd)"
echo "   source .venv/bin/activate && python manage.py runserver"
echo " На сервере (DEBUG=False, ALLOWED_HOSTS и CSRF_TRUSTED_ORIGINS — в .env):"
echo "   .venv/bin/gunicorn config.wsgi -b 127.0.0.1:8070 -w 3 --timeout 120 --daemon"
echo " Админка: http://127.0.0.1:8000/admin/"
echo " Команды — в админке → Система → Команды."
echo "========================================"
