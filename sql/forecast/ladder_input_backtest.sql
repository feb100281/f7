-- Проверка штук на прошлом: раскладываем прогноз выручки, сделанный с отсечки params.cutoff
-- (проверка на прошлом, подборы params.tune_service / params.tune_shop), — как будто это прогноз тогда.
create or replace temp table fc_input as
select tr.series, cast(bp.month as date) as month, cast(bp.yhat as double) as yhat
from db.forecast_backtestpoint bp
join db.forecast_tunerun tr on tr.id = bp.run_id
cross join params p
where bp.run_id in (p.tune_service, p.tune_shop)
  and cast(bp.cutoff as date) = p.cutoff
  and tr.series in ('service', 'shop')
