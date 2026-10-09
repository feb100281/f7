-- Дашборд «Сезонность»: сезон (октябрь – сентябрь) × месяц сезона × канал × группа × подразделение.
-- Вход: temp view lines (_base.sql)
-- Выход: db.mart_season (marts.MartSeason)

drop table if exists db.mart_season;

create table db.mart_season as
select
    row_number() over (order by season, season_month, kind, group_id, department_id)::bigint  as id,
    season,
    season_month,
    kind,
    group_id,
    department_id,
    sum(qty)::double                    as qty,
    sum(revenue)::double                as revenue,
    count(*)::bigint                    as lines
from lines
group by season, season_month, kind, group_id, department_id;
