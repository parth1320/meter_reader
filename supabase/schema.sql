-- Run this once in the Supabase SQL editor.

create table if not exists realtime_reads (
  meter_time        timestamptz primary key,   -- time stamped by the meter
  meter             text not null,
  voltage_v         numeric,
  current_a         numeric,
  frequency_hz      numeric,
  import_kwh        numeric,                   -- cumulative active energy import
  export_kwh        numeric,                   -- cumulative active energy export (solar)
  active_power_kw   numeric,
  apparent_power_kva numeric,
  reactive_power_var numeric,
  md_kw             numeric,                   -- maximum demand
  md_time           timestamptz,
  power_factor      numeric,
  load_limit_w      numeric,
  fetched_at        timestamptz not null default now()
);

create table if not exists monthly_usage (
  month      date primary key,                 -- first day of month
  kwh        numeric,
  demand_kw  numeric
);

create table if not exists bills (
  month   date primary key,
  amount  numeric
);

-- The collector uses the service_role key (bypasses RLS).
-- The dashboard uses the anon key, which may only READ.
alter table realtime_reads enable row level security;
alter table monthly_usage  enable row level security;
alter table bills          enable row level security;

drop policy if exists "anon read" on realtime_reads;
drop policy if exists "anon read" on monthly_usage;
drop policy if exists "anon read" on bills;
create policy "anon read" on realtime_reads for select to anon using (true);
create policy "anon read" on monthly_usage  for select to anon using (true);
create policy "anon read" on bills          for select to anon using (true);
