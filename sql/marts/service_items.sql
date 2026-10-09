-- Дашборд «Сервис»: что уходит в наряды — артикул × месяц × подразделение.
-- Норма на наряд = кол-во за период / число нарядов за период (считается на дашборде).
-- Вход: temp view lines (_base.sql)
-- Выход: db.mart_service_items (marts.MartServiceItems)

drop table if exists db.mart_service_items;

create table db.mart_service_items as
select
    row_number() over (order by item_id, month, department_id)::bigint     as id,
    item_id,
    group_id,
    month,
    department_id,
    count(distinct doc_id)::bigint      as orders,
    sum(qty)::double                    as qty,
    sum(revenue)::double                as revenue,
    sum(cost)::double                   as cost
from lines
where kind = 'service'
group by item_id, group_id, month, department_id;
