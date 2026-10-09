-- Дашборд «Товарные группы»: месяц × товарная группа × канал × подразделение.
-- Группа — на момент пересчёта (после переноса артикулов — «Пересчитать витрины»).
-- Вход: temp view lines (_base.sql)
-- Выход: db.mart_group_month (marts.MartGroupMonth)

drop table if exists db.mart_group_month;

create table db.mart_group_month as
select
    row_number() over (order by month, group_id, kind, department_id)::bigint  as id,
    month,
    group_id,
    kind,
    department_id,
    sum(revenue)::double                    as revenue,
    sum(cost)::double                       as cost,
    sum(qty)::double                        as qty,
    count(*)::bigint                        as lines,
    count(distinct doc_id)::bigint          as docs,
    count(distinct item_id)::bigint         as items
from lines
group by month, group_id, kind, department_id;
