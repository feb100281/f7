-- Лестница: прогноз выручки по рядам → товарные группы → артикулы → штуки.
--
-- Перед запуском Python задаёт params(run_id, data_end): какой прогноз раскладываем
-- и по какую дату есть факт. Результат — temp-таблицы fc_group и fc_item
-- (их читают ladder_groups.sql / ladder_items.sql), промежуточные веса — витрины mart_fc_*.
--
--   ряд → группа:     доля группы в выручке ряда в этом календарном месяце, за 24 полных месяца
--   группа → артикул: штуки артикула за 12 мес. (с гарантией) к «стоимости» продаж группы
--                     за 12 мес. по сегодняшним ценам:
--                       штуки = выручка группы × штуки_12м / Σ(платные штуки_12м × цена)
--                     цена входит только в знаменатель по группе, поэтому рост цен не раздувает
--                     штуки, а гарантийные штуки сидят в числителе и заказываются тоже
--   цена:             медиана за 6 мес. → за 12 мес. → последняя продажа → медиана группы
--   статистика:       по каждому артикулу (вся компания): штуки по 12 полным месяцам с нулями —
--                     среднее, std, CV, сколько месяцев продавался, первая / последняя продажа,
--                     последняя себестоимость штуки (для страхового запаса и выгрузки)
--
-- Группа — текущая из номенклатуры: перенос артикула между группами сразу меняет раскладку.


-- строки продаж: без возвратов и корректировок
create or replace temp view fl as
select
    case when d.kind = 'service' then 'service' else 'shop' end   as series,
    l.item_id                                                     as item_id,
    i.group_id                                                    as group_id,
    cast(d.date as date)                                          as date,
    cast(l.qty as double)                                         as qty,
    cast(coalesce(l.revenue, 0) as double)                        as revenue,
    cast(coalesce(l.cost, 0) as double)                           as cost
from db.sales_salesline l
join db.sales_salesdoc d on d.id = l.doc_id
join db.catalog_item i on i.id = l.item_id
where d.kind in ('service', 'sale', 'retail');


-- 1. Веса групп по календарным месяцам (2 последних сезона = 24 полных месяца до текущего)
drop table if exists db.mart_fc_group_weight;
create table db.mart_fc_group_weight as
with bounds as (
    select
        cast(date_trunc('month', data_end) as date)                          as cur_month,
        cast(date_trunc('month', data_end) - interval 24 month as date)      as from_month
    from params
),
w as (
    select fl.series, fl.group_id, cast(month(fl.date) as integer) as moy, sum(fl.revenue) as revenue
    from fl, bounds b
    where fl.date >= b.from_month and fl.date < b.cur_month
    group by fl.series, fl.group_id, month(fl.date)
)
select
    cast(row_number() over (order by series, moy, group_id) as bigint)       as id,
    series,
    group_id,
    moy,
    revenue,
    revenue / nullif(sum(revenue) over (partition by series, moy), 0)        as share
from w;


-- 2. Цена артикула (одна на артикул, по всем каналам) — лесенка источников
drop table if exists db.mart_fc_price;
create table db.mart_fc_price as
with b as (
    select
        cast(data_end - interval 6 month as date)    as from6,
        cast(data_end - interval 12 month as date)   as from12
    from params
),
paid as (
    select fl.item_id, fl.group_id, fl.date, fl.revenue / fl.qty as unit
    from fl
    where fl.revenue > 0 and fl.qty > 0
),
by_item as (
    select
        paid.item_id,
        any_value(paid.group_id)                                     as group_id,
        median(paid.unit) filter (where paid.date > b.from6)          as price6,
        median(paid.unit) filter (where paid.date > b.from12)         as price12,
        arg_max(paid.unit, paid.date)                                 as price_last,
        max(paid.date)                                                as last_paid
    from paid, b
    group by paid.item_id, b.from6, b.from12
),
items as (  -- артикулы с движением за 12 мес. (в т.ч. только гарантия)
    select distinct fl.item_id, fl.group_id
    from fl, b
    where fl.date > b.from12
),
by_group as (
    select group_id, median(coalesce(price6, price12)) as price_group
    from by_item
    group by group_id
)
select
    cast(row_number() over (order by items.item_id) as bigint)                 as id,
    items.item_id,
    items.group_id,
    coalesce(bi.price6, bi.price12, bi.price_last, bg.price_group)             as price,
    case
        when bi.price6 is not null then '6m'
        when bi.price12 is not null then '12m'
        when bi.price_last is not null then 'last'
        when bg.price_group is not null then 'group'
        else 'none'
    end                                                                        as price_source,
    bi.last_paid
from items
left join by_item bi on bi.item_id = items.item_id
left join by_group bg on bg.group_id is not distinct from items.group_id;


-- 3. Доли артикулов внутри группы по ряду: штуки за 12 мес. и стоимость платных продаж группы
drop table if exists db.mart_fc_item_weight;
create table db.mart_fc_item_weight as
with b as (
    select cast(data_end - interval 12 month as date) as from12 from params
),
q as (
    select
        fl.series,
        fl.item_id,
        fl.group_id,
        sum(fl.qty)                                          as qty12,
        coalesce(sum(fl.qty) filter (where fl.revenue > 0), 0)  as paid_qty12
    from fl, b
    where fl.date > b.from12
    group by fl.series, fl.item_id, fl.group_id
)
select
    cast(row_number() over (order by q.series, q.group_id, q.item_id) as bigint)   as id,
    q.series,
    q.item_id,
    q.group_id,
    q.qty12,
    q.paid_qty12,
    pr.price,
    pr.price_source,
    sum(q.paid_qty12 * coalesce(pr.price, 0)) over (partition by q.series, q.group_id)  as group_value
from q
left join db.mart_fc_price pr on pr.item_id = q.item_id
where q.qty12 > 0;


-- 4. Раскладка прогноза
create or replace temp table fc_group as
with fp as (
    select fp.series, cast(fp.month as date) as month, cast(fp.yhat as double) as yhat
    from db.forecast_forecastpoint fp, params p
    where fp.run_id = p.run_id and fp.series in ('service', 'shop')
)
select
    fp.series,
    fp.month,
    gw.group_id,
    gw.share,
    fp.yhat * gw.share                      as revenue
from fp
join db.mart_fc_group_weight gw on gw.series = fp.series and gw.moy = month(fp.month)
where gw.share > 0;

create or replace temp table fc_item as
select
    g.series,
    g.month,
    g.group_id,
    iw.item_id,
    g.revenue * iw.qty12 / iw.group_value                           as qty,
    g.revenue * iw.paid_qty12 * coalesce(iw.price, 0) / iw.group_value  as revenue,
    iw.price,
    iw.price_source
from fc_group g
join db.mart_fc_item_weight iw
    on iw.series = g.series and iw.group_id is not distinct from g.group_id
where iw.group_value > 0;


-- 5. Статистика артикулов по всей компании (сервис + продажи): спрос по месяцам с нулями
--    CV считается по 12 полным месяцам, нулевые месяцы входят: продажа рывками = высокий CV
drop table if exists db.mart_fc_item_stats;
create table db.mart_fc_item_stats as
with b as (
    select
        cast(date_trunc('month', data_end) as date)                       as cur_month,
        cast(date_trunc('month', data_end) - interval 12 month as date)   as from12,
        cast(date_trunc('month', data_end) - interval 24 month as date)   as from24
    from params
),
months as (
    select cast(unnest(generate_series(
        cast(b.from12 as timestamp), cast(b.cur_month - interval 1 month as timestamp), interval 1 month
    )) as date) as month
    from b
),
mq as (
    select fl.item_id, cast(date_trunc('month', fl.date) as date) as month, sum(fl.qty) as qty
    from fl, b
    where fl.date >= b.from24 and fl.date < b.cur_month
    group by fl.item_id, cast(date_trunc('month', fl.date) as date)
),
items as (
    select distinct item_id from mq
),
grid as (
    select items.item_id, months.month, coalesce(mq.qty, 0) as qty
    from items
    cross join months
    left join mq on mq.item_id = items.item_id and mq.month = months.month
),
s12 as (
    select
        item_id,
        sum(qty)                                  as qty12,
        count(*) filter (where qty > 0)           as months12,
        avg(qty)                                  as mean12,
        stddev_pop(qty)                           as std12
    from grid
    group by item_id
),
s24 as (
    select item_id, sum(qty) as qty24, count(*) filter (where qty > 0) as months24
    from mq
    group by item_id
),
life as (
    select
        fl.item_id,
        min(fl.date)                                                                  as first_sale,
        max(fl.date)                                                                  as last_sale,
        arg_max(fl.cost / fl.qty, fl.date) filter (where fl.cost > 0 and fl.qty > 0)  as last_cost,
        max(fl.date) filter (where fl.cost > 0 and fl.qty > 0)                        as last_cost_date
    from fl
    group by fl.item_id
)
select
    s12.item_id,
    s12.qty12,
    cast(s12.months12 as integer)                                  as months12,
    s12.mean12,
    s12.std12,
    case when s12.mean12 > 0 then s12.std12 / s12.mean12 end        as cv12,
    s24.qty24,
    cast(s24.months24 as integer)                                  as months24,
    life.first_sale,
    life.last_sale,
    life.last_cost,
    life.last_cost_date
from s12
join s24 on s24.item_id = s12.item_id
join life on life.item_id = s12.item_id;
