"""
Проверка штук на прошлом: каждый номер отдельно против склейки номеров.

    python manage.py forecast_qty_check
Параметры задачи:
    months: сколько месяцев вперёд сравнивать (по умолчанию 6)

Берёт прогнозы выручки с прошлых отсечек (последний «Прогноз: подбор параметров» по сервису
и продажам), раскладывает их лестницей по тогдашним данным и сравнивает штуки с фактом.
Результат — «Прогноз → Проверка на прошлом», блок «Штуки».
"""

from core.management.base import JobCommand
from core.models.jobs import JobTypes


class Command(JobCommand):
    help = "Проверка прогноза в штуках на прошлом: как сейчас против склейки номеров"

    job_name = "Прогноз: проверка штук на прошлом"
    job_type = JobTypes.ETL
    job_description = (
        "<h2><u>Проверка штук на прошлом</u></h2>"
        "<p>С каждой прошлой отсечки раскладывает тогдашний прогноз выручки по артикулам и сравнивает "
        "штуки с фактом за 6 месяцев — в двух вариантах: каждый номер отдельно и со склейкой старых "
        "номеров с актуальными («Номенклатура → Замены номеров»). Нужен готовый подбор параметров "
        "по сервису и продажам. В конце пересобирает раскладку текущего прогноза.</p>"
        "<pre>Параметры:\\nmonths: месяцев вперёд (6)</pre>"
    )
    job_param = {"months": 6}

    def run(self, params: dict):
        from forecast.services.qty_check import qty_check, summary

        months = int(params.get("months") or 6)
        self.step(f"Проверка штук на {months} мес.")
        check = qty_check(months=months, log=self.stdout.write)
        s = summary(check)
        if s:
            self.step("Итог")
            for v in s["variants"]:
                self.stdout.write(f"   {v['label']:<38} ошибка {v['all']['err']:.1%}, "
                                  f"по артикулам с заменами {v['fam']['err']:.1%}")
        self.ok("Готово")
