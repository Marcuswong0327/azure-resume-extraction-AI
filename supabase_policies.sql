-- RLS policies for the publishable/anon key (SUPABASE_KEY).
-- Safe to re-run: drops existing policies first, then recreates them.
-- Run in Supabase SQL Editor after supabase_schema.sql.

drop policy if exists "Allow read for anon" on public.candidates;
drop policy if exists "Allow insert for anon" on public.candidates;
drop policy if exists "Allow update for anon" on public.candidates;

create policy "Allow read for anon"
  on public.candidates for select
  to anon using (true);

create policy "Allow insert for anon"
  on public.candidates for insert
  to anon with check (true);

create policy "Allow update for anon"
  on public.candidates for update
  to anon using (true) with check (true);
