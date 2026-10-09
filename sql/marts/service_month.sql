-- Дашборд «Сервис»: наряды по месяцам × подразделение.
-- Наряд без выручки целиком (сумма по наряду = 0) считаем гарантийным/внутренним.
-- Вход: temp view lines (_base.sql)
-- Выход: db.mart_service_month (marts.MartServiceMonth)

drop table if exists db.mart_service_month;

create table db.mart_service_month as
with orders as (
    select
        doc_id,
        month,
        department_id,
        count(*)                                                as lines,
        sum(qty)                                                as qty,
        sum(qty) filter (where demand_type = 'consumable')      as qty_consumable,
        bool_or(demand_type = 'consumable')                     as has_consumable,
        sum(revenue)                                            as revenue,
        sum(cost)                                               as cost
    from lines
    where kind = 'service'
    group by doc_id, month, department_id
)
select
    row_number() over (order by month, department_id)::bigint      as id,
    month,
    department_id,
    count(*)::bigint                                            as orders,
    count(*) filter (where has_consumable)::bigint              as orders_consumable,
    count(*) filter (where revenue = 0)::bigint                 as orders_no_revenue,
    sum(lines)::bigint                                          as lines,
    sum(qty)::double                                            as qty,
    coalesce(sum(qty_consumable), 0)::double                    as qty_consumable,
    sum(revenue)::double                                        as revenue,
    sum(cost)::double                                           as cost
from orders
group by month, department_id;
