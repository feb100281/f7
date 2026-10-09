"""
Подбор параметров прогноза (Prophet) на прошлом — rolling-бэктест по сетке параметров.

    python manage.py forecast_tune
Параметры задачи:
    series:         ряды — ["service", "shop"]
    horizon:        горизонт проверки, мес. (6)
    step_months:    шаг между отсечками, мес. (2)
    min_train_days: минимум истории для обучения на каждой отсечке, дней (730)
    workers:        процессов (0 — все ядра, кроме одного)
    grid:           сетка параметров ({} — по умолчанию, см. forecast/services/engine.py)
    build_after:    сразу построить прогноз с лучшими параметрами (true)
"""

from core.management.base import JobCommand
from core.models.jobs import JobTypes


class Command(JobCommand):
    help = "Подбор параметров прогноза на прошлом (rolling-бэктест)"

    job_name = "Прогноз: подбор параметров"
    job_type = JobTypes.ETL
    job_description = (
        "<h2><u>Подбор параметров прогноза</u></h2>"
        "<p>Для каждого ряда (сервис; реализация + розница) перебирает параметры Prophet: окно обучения, "
        "чистку крупных разовых документов, гибкость тренда, силу сезонности, дни или недели. Каждая "
        "комбинация прогнозирует с нескольких дат в прошлом на горизонт вперёд и сравнивается с фактом. "
        "Побеждает минимальная средняя ошибка. Результаты — в «Прогноз → Проверка на прошлом». "
        "Запускать редко: раз в квартал или после загрузки большого куска новых данных.</p>"
        "<pre>Параметры:\\nseries: ряды\\nhorizon: горизонт, мес.\\nstep_months: шаг отсечек, мес.\\n"
        "min_train_days: минимум истории, дней\\nworkers: процессов (0 — авто)\\n"
        "grid: своя сетка ({} — по умолчанию)\\nbuild_after: сразу построить прогноз</pre>"
    )
    job_param = {
        "series": ["service", "shop"],
        "horizon": 6,
        "step_months": 2,
        "min_train_days": 730,
        "workers": 0,
        "grid": {},
        "build_after": True,
    }

    def run(self, params: dict):
        from forecast.models import Series
        from forecast.services.build import build
        from forecast.services.tune import tune

        horizon = int(params.get("horizon", 6))
        for series in params.get("series") or ["service", "shop"]:
            self.step(f"Подбор: {Series(series).label}")
            run = tune(
                series,
                grid=params.get("grid") or None,
                horizon=horizon,
                step=int(params.get("step_months", 2)),
                min_train_days=int(params.get("min_train_days", 730)),
                workers=int(params.get("workers", 0)),
                log=self.stdout.write,
            )
            self.stdout.write(f"   за {run.seconds:.0f} c")

        if params.get("build_after", True):
            self.step("Прогноз с подобранными параметрами")
            build(horizon=horizon, note="после подбора", log=self.stdout.write)
        self.ok("Готово")
