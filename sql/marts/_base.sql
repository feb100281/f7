-- Общая основа для всех витрин: строки продаж с документом, артикулом и текущей товарной группой.
-- Временное представление живёт только в сессии пересчёта (build_marts выполняет файлы
-- по порядку в одном подключении), поэтому этот файл идёт в MARTS первым.
-- Вход: db.sales_salesline, db.sales_salesdoc, db.catalog_item, db.catalog_itemgroup
--
-- НДС: в 1С выручка (цена продажи) — с НДС, себестоимость — без НДС. Для маржи выручка
-- приводится к «без НДС» по ставке на дату документа: 18% до 2019, 20% в 2019–2025, 22% с 2026.

create or replace temp view lines as
select
    l.id::bigint                                    as line_id,
    l.doc_id::bigint                                as doc_id,
    l.item_id::bigint                               as item_id,
    i.group_id::bigint                              as group_id,
    coalesce(g.demand_type, 'other')::varchar       as demand_type,
    d.kind::varchar                                 as kind,
    d.department_id::bigint                         as department_id,
    d.date::date                                    as date,
    date_trunc('month', d.date::date)::date         as month,
    -- сезон: октябрь – сентябрь, называется по году начала (сезон 2025 = 10.2025–09.2026)
    (case when month(d.date::date) >= 10 then year(d.date::date) else year(d.date::date) - 1 end)::bigint
                                                    as season,
    -- месяц сезона: октябрь = 1 … сентябрь = 12
    ((month(d.date::date) + 2) % 12 + 1)::bigint    as season_month,
    l.qty::double                                   as qty,
    coalesce(l.revenue, 0)::double                  as revenue,
    (case
        when d.date::date < date '2019-01-01' then 0.18
        when d.date::date < date '2026-01-01' then 0.20
        else 0.22
     end)::double                                   as vat_rate,
    (coalesce(l.revenue, 0) / (1 + case
        when d.date::date < date '2019-01-01' then 0.18
        when d.date::date < date '2026-01-01' then 0.20
        else 0.22
     end))::double                                  as revenue_net,
    coalesce(l.cost, 0)::double                     as cost,
    (l.revenue is null)                             as no_revenue
from db.sales_salesline l
join db.sales_salesdoc   d on d.id = l.doc_id
join db.catalog_item     i on i.id = l.item_id
left join db.catalog_itemgroup g on g.id = i.group_id;
