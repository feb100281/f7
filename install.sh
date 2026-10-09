#!/usr/bin/env bash
# ============================================================
#  FORMULA7 · Хелпер отдела продаж запчастей — установка проекта
#
#  Положить install.sh в любую папку (например ~/prj) и запустить:
#      bash install.sh            → клонирует репо в ./f7 и ставит
#      bash install.sh mydir      → то же, в ./mydir
#  Если скрипт запущен прямо в папке проекта — просто git pull и установка.
#
#  Локальная версия: база SQLite (db.sqlite3 в папке проекта).
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
    else
        echo "  ОШИБКА: нужен python3.12 (brew install python@3.12 или https://www.python.org)"
        exit 1
    fi
fi

echo
echo "— Виртуальное окружение (python 3.12)"
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

echo
echo "— Зависимости"
pip install -r requirements.txt

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
ENV
fi

echo
echo "— Миграции"
python manage.py migrate

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
    echo "  укажите source в админке → Система → Команды → «Импорт продаж из 1С» и запустите её"
fi

echo
echo "========================================"
echo " Готово. Запуск:"
echo "   cd $(pwd)"
echo "   source .venv/bin/activate && python manage.py runserver"
echo " Админка: http://127.0.0.1:8000/admin/"
echo " Команды — в админке → Система → Команды."
echo "========================================"
