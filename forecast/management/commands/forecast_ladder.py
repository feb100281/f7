"""
Прогноз в штуках: раскладка прогноза выручки по товарным группам и артикулам (лестница).

    python manage.py forecast_ladder
Параметры задачи:
    run: id прогноза (пусто — последний)

Сама запускается в конце «Прогноз: построить». Руками — после переноса артикулов
между группами: раскладка берёт текущие группы из номенклатуры.
"""

from core.management.base import JobCommand
from core.models.jobs import JobTypes


class Command(JobCommand):
    help = "Прогноз в штуках по группам и артикулам (лестница)"

    job_name = "Прогноз: штуки по артикулам"
    job_type = JobTypes.ETL
    job_description = (
        "<h2><u>Прогноз в штуках</u></h2>"
        "<p>Раскладывает прогноз выручки (сервис и реализация + розница) по товарным группам — "
        "по их доле в этом календарном месяце за 2 последних сезона, — затем по артикулам — по штукам "
        "за 12 мес. с гарантией — и переводит в штуки по свежей цене. Результат — «Прогноз → Штуки». "
        "Запускается сама после «Прогноз: построить»; руками — после переноса артикулов между группами.</p>"
        "<pre>Параметры:\\nrun: id прогноза (пусто — последний)</pre>"
    )
    job_param = {"run": None}

    def run(self, params: dict):
        from forecast.models import ForecastRun
        from forecast.services.ladder import ladder

        run = ForecastRun.objects.filter(pk=params["run"]).first() if params.get("run") else ForecastRun.objects.first()
        if not run:
            raise ValueError("Прогноза ещё нет — сначала «Прогноз: построить».")
        self.step(f"Лестница: {run}")
        ladder(run, log=self.stdout.write)
        self.ok("Готово")
