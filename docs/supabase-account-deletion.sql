-- Run once in your project's SQL editor to enable authenticated self-deletion.
-- The application can alternatively use a server-only SUPABASE_SERVICE_ROLE_KEY.
create or replace function public.delete_own_account()
returns void language plpgsql security definer set search_path = pg_catalog
as $$
declare current_user_id uuid := auth.uid();
begin
  if current_user_id is null then raise exception 'Authentication required'; end if;
  delete from auth.users where id = current_user_id;
end;
$$;
revoke all on function public.delete_own_account() from public, anon;
grant execute on function public.delete_own_account() to authenticated;
