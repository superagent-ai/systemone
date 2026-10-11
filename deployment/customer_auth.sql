-- Applied to Superagent production on 2026-09-28 with operator approval.
-- Supabase migration: systemone_key_lookup_rpc_and_helper_permissions.
-- Audit artifact only: do not execute automatically during application deployment.
-- Existing explicit anon/authenticated/service_role helper grants are preserved.
REVOKE EXECUTE ON FUNCTION public.is_org_owner(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.is_org_member(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_organization_members_with_users(uuid) FROM PUBLIC;

CREATE FUNCTION public.systemone_api_key_lookup(p_key_hash text)
RETURNS TABLE(id uuid, organization_id uuid)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $function$
  SELECT ak.id, ak.organization_id FROM public.api_keys AS ak
  WHERE ak.key_hash = p_key_hash LIMIT 2;
$function$;

REVOKE ALL ON FUNCTION public.systemone_api_key_lookup(text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.systemone_api_key_lookup(text) TO service_role;
NOTIFY pgrst, 'reload schema';
