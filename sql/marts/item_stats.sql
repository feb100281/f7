-- Витрина: статистика продаж по артикулу (одна строка на артикул, ключ — item_id).
-- Отсюда же после пересчёта обновляются поля статистики в карточке артикула (catalog_item).
-- Вход:  db.mart_item_month (сначала item_month.sql)
-- Таблицы mart_* DuckDB хранит в SQLite текстом/числами без строгих типов —
-- при чтении обратно типы приводим явно (CTE mm).
-- Выход: db.mart_item_stats  (модель marts.MartItemStats, managed = False)

drop table if exists db.mart_item_stats;

create table db.mart_item_stats as
with mm as (
    select
        item_id::bigint     as item_id,
        month::date         as month,
        kind::varchar       as kind,
        qty::double         as qty,
        revenue::double     as revenue,
        cost::double        as cost,
        docs::bigint        as docs
    from db.mart_item_month
),
bounds as (
    select max(month) as max_month from mm
),
by_item as (
    select
        item_id,
        min(month)                                                  as first_month,
        max(month)                                                  as last_month,
        sum(qty)                                                    as qty,
        sum(revenue)                                                as revenue,
        sum(cost)                                                   as cost,
        sum(docs)                                                   as docs,
        count(distinct month)                                       as months,
        count(distinct month) filter (where month > (select max_month from bounds) - interval 12 month) as months_12,
        sum(qty) filter (where month > (select max_month from bounds) - interval 12 month)              as qty_12,
        sum(qty) filter (where kind = 'service')                    as qty_service,
        sum(qty) filter (where kind = 'sale')                       as qty_sale,
        sum(qty) filter (where kind = 'retail')                     as qty_retail
    from mm
    group by item_id
),
dates as (
    select l.item_id::bigint as item_id, min(d.date::date) as first_sale, max(d.date::date) as last_sale
    from db.sales_salesline l
    join db.sales_salesdoc d on d.id = l.doc_id
    group by l.item_id
)
select
    b.item_id::bigint                       as item_id,
    t.first_sale::date                      as first_sale,
    t.last_sale::date                       as last_sale,
    coalesce(b.qty, 0)::double              as qty,
    coalesce(b.revenue, 0)::double          as revenue,
    coalesce(b.cost, 0)::double             as cost,
    coalesce(b.docs, 0)::bigint             as docs,
    coalesce(b.months, 0)::bigint           as months,
    coalesce(b.months_12, 0)::bigint        as months_12,
    coalesce(b.qty_12, 0)::double           as qty_12,
    coalesce(b.qty_service, 0)::double      as qty_service,
    coalesce(b.qty_sale, 0)::double         as qty_sale,
    coalesce(b.qty_retail, 0)::double       as qty_retail
from by_item b
left join dates t using (item_id);
