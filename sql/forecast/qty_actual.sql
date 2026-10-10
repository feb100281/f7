-- Факт штук по артикулам (или семействам, params.families) с params.cutoff на params.months месяцев:
-- с чем сравниваем раскладку в проверке на прошлом. Каналы те же, что у лестницы.
select
    case when p.families then coalesce(i0.family_head_id, i0.id) else i0.id end   as item_id,
    sum(cast(l.qty as double))                                                     as qty
from db.sales_salesline l
join db.sales_salesdoc d on d.id = l.doc_id
join db.catalog_item i0 on i0.id = l.item_id
cross join params p
where d.kind in ('service', 'sale', 'retail')
  and cast(d.date as date) >= p.cutoff
  and cast(d.date as date) < cast(p.cutoff + to_months(cast(p.months as integer)) as date)
group by 1
