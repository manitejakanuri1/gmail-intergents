-- Adds priority/urgency + action classification for the control dashboard.
alter table emails add column if not exists priority text;        -- 'urgent' | 'high' | 'medium' | 'low'
alter table emails add column if not exists action_item text;     -- what the user should do, if anything
alter table emails add column if not exists needs_action boolean default false;

-- Fetch the dashboard ordered by urgency quickly.
create index if not exists idx_emails_priority on emails (
  account_id,
  (case priority when 'urgent' then 1 when 'high' then 2 when 'medium' then 3 when 'low' then 4 else 5 end),
  internal_date desc
);
