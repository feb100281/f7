-- Что раскладывает лестница: прогноз выручки ForecastRun (params.run_id) по рядам сервис / продажи.
create or replace temp table fc_input as
select fp.series, cast(fp.month as date) as month, cast(fp.yhat as double) as yhat
from db.forecast_forecastpoint fp, params p
where fp.run_id = p.run_id and fp.series in ('service', 'shop')
