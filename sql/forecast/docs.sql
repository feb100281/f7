-- Прогноз: выручка по документам (дата, ряд, документ, сумма).
-- Ряды: service — наряды, shop — реализация + розница. Возвраты и корректировки не входят.
-- Документы нужны, а не дневные суммы: по ним отсекаются крупные разовые отгрузки (выбросы).
select
    d.date                                                         as date,
    case when d.kind = 'service' then 'service' else 'shop' end    as series,
    d.id                                                           as doc_id,
    cast(sum(coalesce(l.revenue, 0)) as double)                    as revenue
from db.sales_salesdoc d
join db.sales_salesline l on l.doc_id = d.id
where d.kind in ('service', 'sale', 'retail')
group by d.date, d.kind, d.id
