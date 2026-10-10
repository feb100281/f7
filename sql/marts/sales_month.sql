-- Дашборды «Обзор продаж» и «Салоны»: месяц × канал × подразделение.
-- revenue — с НДС (как в 1С), revenue_net — без НДС (для маржи: revenue_net − cost).
-- Вход: temp view lines (_base.sql)
-- Выход: db.mart_sales_month (marts.MartSalesMonth)

drop table if exists db.mart_sales_month;

create table db.mart_sales_month as
select
    row_number() over (order by month, kind, department_id)::bigint    as id,
    month,
    kind,
    department_id,
    sum(revenue)::double                                as revenue,
    sum(revenue_net)::double                                as revenue_net,
    sum(cost)::double                                   as cost,
    sum(qty)::double                                    as qty,
    count(distinct doc_id)::bigint                      as docs,
    count(*)::bigint                                    as lines,
    count(*) filter (where no_revenue)::bigint          as lines_no_revenue,
    count(distinct item_id)::bigint                     as items
from lines
group by month, kind, department_id;
