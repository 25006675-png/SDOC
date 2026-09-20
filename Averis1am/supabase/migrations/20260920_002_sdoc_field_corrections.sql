-- Correct Extraction (v2 §9): a worker replaces a wrongly extracted value,
-- the previous value is kept as evidence, and the case is re-decided.
--
-- The comparison itself is recomputed in Python (sdoc.casework.apply_correction)
-- so the rules live in one place; this function only persists the outcome
-- atomically and keeps the audit trail complete.

create table if not exists public.field_corrections (
  correction_id bigint generated always as identity primary key,
  case_id       text not null references public.shipment_cases(case_id),
  comparison_id bigint not null references public.comparisons(comparison_id),
  field         text not null,
  side          text not null check (side in ('si','bl')),
  old_value     text,
  new_value     text,
  actor         text not null,
  note          text,
  created_at    timestamptz not null
);

create index if not exists field_corrections_case_idx
  on public.field_corrections(case_id, correction_id);

create or replace function public.correct_sdoc_field(
  p_case_id text,
  p_comparison_id bigint,
  p_field text,
  p_side text,
  p_old_value text,
  p_new_value text,
  p_state text,
  p_reason text,
  p_defect_fields jsonb,
  p_evidence jsonb,
  p_actor text,
  p_note text,
  p_now double precision
) returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_now timestamptz := to_timestamp(p_now);
  v_previous_state text;
  v_task_id bigint;
begin
  select state into v_previous_state from shipment_cases
    where case_id=p_case_id for update;
  if v_previous_state is null then
    raise exception 'case not found';
  end if;

  update comparisons set
    state=p_state,
    defect_fields=p_defect_fields,
    evidence_json=p_evidence
  where comparison_id=p_comparison_id and case_id=p_case_id;
  if not found then
    raise exception 'comparison not found for case';
  end if;

  insert into field_corrections(case_id,comparison_id,field,side,
                                old_value,new_value,actor,note,created_at)
  values(p_case_id,p_comparison_id,p_field,p_side,
         p_old_value,p_new_value,p_actor,p_note,v_now);

  update shipment_cases set
    state=p_state,
    state_reason=p_reason,
    updated_at=v_now,
    waiting_since=case when p_state='WAITING' then coalesce(waiting_since,v_now)
                       else null end
  where case_id=p_case_id;

  if v_previous_state is distinct from p_state then
    insert into audit_events(case_id,event_type,actor,detail_json,created_at)
    values(p_case_id,'STATE_CHANGED',p_actor,
           jsonb_build_object('from',v_previous_state,'to',p_state,
                              'reason',p_reason),v_now);
  end if;

  select task_id into v_task_id from review_tasks
    where case_id=p_case_id and status='OPEN' limit 1;
  if p_state in ('DISCREPANCY','NEEDS_REVIEW','BLOCKED') then
    if v_task_id is null then
      insert into review_tasks(case_id,kind,reason,created_at)
      values(p_case_id,p_state,p_reason,v_now);
      insert into audit_events(case_id,event_type,actor,detail_json,created_at)
      values(p_case_id,'REVIEW_TASK_CREATED',p_actor,
             jsonb_build_object('kind',p_state,'reason',p_reason),v_now);
    else
      update review_tasks set kind=p_state,reason=p_reason
        where task_id=v_task_id;
    end if;
  elsif v_task_id is not null then
    update review_tasks set status='RESOLVED',assignee=p_actor,resolved_at=v_now,
      resolution_note='Resolved by extraction correction'
      where task_id=v_task_id;
  end if;

  insert into audit_events(case_id,event_type,actor,detail_json,created_at)
  values(p_case_id,'EXTRACTION_CORRECTED',p_actor,
         jsonb_build_object('field',p_field,'side',p_side,
                            'from',p_old_value,'to',p_new_value,
                            'note',p_note,'new_state',p_state),v_now);

  return p_case_id;
end;
$$;

alter table public.field_corrections enable row level security;

revoke all on function public.correct_sdoc_field(
  text,bigint,text,text,text,text,text,text,jsonb,jsonb,text,text,double precision)
  from public, anon, authenticated;
grant execute on function public.correct_sdoc_field(
  text,bigint,text,text,text,text,text,text,jsonb,jsonb,text,text,double precision)
  to service_role;
