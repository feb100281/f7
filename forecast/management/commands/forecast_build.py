"""
Прогноз выручки на N месяцев вперёд (Prophet) с параметрами последнего подбора.

    python manage.py forecast_build
Параметры задачи:
    horizon: месяцев вперёд после текущего (6)
    note:    комментарий к прогнозу

Каждый прогноз сохраняется — когда придёт новый факт, на «Проверке на прошлом» видно,
насколько он попал. Подбора ещё не было — берутся параметры Prophet по умолчанию.
"""

from core.management.base import JobCommand
from core.models.jobs import JobTypes


class Command(JobCommand):
    help = "Прогноз выручки по сервису и реализации + рознице"

    job_name = "Прогноз: построить"
    job_type = JobTypes.ETL
    job_description = (
        "<h2><u>Прогноз выручки</u></h2>"
        "<p>Prophet обучается на всей истории до последней даты продаж и прогнозирует остаток "
        "текущего месяца и N месяцев вперёд — отдельно сервис и реализацию + розницу, «Всего» — сумма. "
        "Параметры — из последнего подбора. Запускать после каждой загрузки продаж. "
        "Каждый прогноз сохраняется, чтобы потом сравнить с фактом.</p>"
        "<pre>Параметры:\\nhorizon: месяцев вперёд (6)\\nnote: комментарий</pre>"
    )
    job_param = {"horizon": 6, "note": ""}

    def run(self, params: dict):
        from forecast.services.build import build

        self.step("Прогноз")
        run = build(horizon=int(params.get("horizon", 6)), note=params.get("note") or "", log=self.stdout.write)
        self.ok(f"Готово за {run.seconds:.0f} c")
