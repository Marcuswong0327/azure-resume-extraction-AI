-- Candidates table for the Global Search tab.
-- Run this in Supabase: Dashboard -> SQL Editor -> New query -> paste -> Run.

create table public.candidates (
  id           uuid primary key default gen_random_uuid(),
  country      text,                    -- 'AU' or 'MY'
  role_type    text,
  full_name    text,
  first_name   text,
  last_name    text,
  mobile       text,
  email        text,
  duration_1   text,
  job_title_1  text,
  company_1    text,
  duration_2   text,
  job_title_2  text,
  company_2    text,
  duration_3   text,
  job_title_3  text,
  company_3    text,
  location     text,
  source_file  text,                    -- Azure blob URL or original filename
  blob_path    text unique,             -- e.g. 'MY/<sha256>.pdf'; unique so re-uploads don't duplicate
  created_at   timestamptz not null default now()
);

-- Always enable RLS so the table is not publicly readable by default.
alter table public.candidates enable row level security;

-- OPTION A (recommended for this app): use the SECRET key in SUPABASE_KEY.
-- The secret key bypasses RLS, so no policies are needed. Nothing more to run.

-- OPTION B: if you use the publishable/anon key, run supabase_policies.sql
-- after creating this table.
