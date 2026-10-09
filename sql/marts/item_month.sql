-- Витрина-обозреватель: артикул × месяц × канал × подразделение (для разбора и будущего прогноза).
-- Группы здесь нет — в админке она берётся через артикул (item → group), всегда текущая.
-- Вход: temp view lines (_base.sql)
-- Выход: db.mart_item_month (marts.MartItemMonth)

drop table if exists db.mart_item_month;

create table db.mart_item_month as
select
    row_number() over (order by item_id, month, kind, department_id)::bigint  as id,
    item_id,
    month,
    kind,
    department_id,
    sum(qty)::double                                as qty,
    sum(revenue)::double                            as revenue,
    sum(cost)::double                               as cost,
    count(distinct doc_id)::bigint                  as docs,
    count(*)::bigint                                as lines,
    count(*) filter (where no_revenue)::bigint      as lines_no_revenue
from lines
group by item_id, month, kind, department_id;
