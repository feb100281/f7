-- Отметка о пересчёте витрин — последним файлом в MARTS.
-- Дашборды сравнивают её со временем правок номенклатуры и показывают «витрины устарели».
-- Время — unix-секунды (целое), чтобы не зависеть от формата дат в SQLite.

drop table if exists db.mart_meta;

create table db.mart_meta as
select
    1::bigint                                               as id,
    epoch(now())::bigint                                    as built_at,
    (select max(month) from lines)::date                    as last_month,
    (select max(date) from lines)::date                     as last_date,
    (select count(*) from lines)::bigint                    as lines;
