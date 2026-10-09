create or replace temp table sales as 
select * from read_parquet('data/parquet/sales/sales_lines.parquet');

select sum(revenue) from sales