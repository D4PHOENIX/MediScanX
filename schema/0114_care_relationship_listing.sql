-- 0114_care_relationship_listing.sql

CREATE OR REPLACE FUNCTION public.list_care_relationships()
RETURNS TABLE (
    id uuid,
    status text,
    is_active boolean,
    created_at timestamptz,
    activated_at timestamptz,
    expires_at timestamptz,
    doctor_full_name text,
    doctor_specialization text,
    doctor_current_hospital text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $$
DECLARE
    v_uid uuid := auth.uid();
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'Not authenticated';
    END IF;

    RETURN QUERY
    SELECT 
        cr.id,
        cr.status,
        (cr.status = 'active' AND (cr.expires_at IS NULL OR cr.expires_at > now())) AS is_active,
        cr.created_at,
        cr.activated_at,
        cr.expires_at,
        dp.full_name,
        dp.specialization,
        dp.current_hospital
    FROM public.care_relationships cr
    LEFT JOIN public.doctor_profiles dp ON dp.user_id = cr.doctor_id
    WHERE cr.patient_id = v_uid
      AND cr.status IN ('pending', 'active');
END;
$$;
