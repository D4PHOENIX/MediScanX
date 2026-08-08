-- MediScanX canonical auth -> profile sync contract
-- Apply in Supabase SQL editor.
-- This function reads metadata from auth.users.raw_user_meta_data and
-- creates/updates either patient_records or doctor_profiles.

alter table if exists public.patient_records
  add column if not exists date_of_birth text;

alter table if exists public.doctor_profiles
  add column if not exists date_of_birth text;

create or replace function public.handle_new_user_profile()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_role text := coalesce(new.raw_user_meta_data ->> 'role', new.raw_user_meta_data ->> 'userType', 'Patient');
  v_full_name text := coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'fullName', 'Unknown User');
  v_username text := coalesce(new.raw_user_meta_data ->> 'username', split_part(new.email, '@', 1));
  v_phone text := nullif(new.raw_user_meta_data ->> 'phone_number', '');
  v_gender text := nullif(new.raw_user_meta_data ->> 'gender', '');
  v_date_of_birth text := nullif(new.raw_user_meta_data ->> 'date_of_birth', '');
  v_location text := nullif(new.raw_user_meta_data ->> 'location', '');
  v_specialization text := nullif(new.raw_user_meta_data ->> 'specialization', '');
  v_current_hospital text := nullif(new.raw_user_meta_data ->> 'current_hospital', '');
begin
  if lower(v_role) = 'doctor' then
    insert into public.doctor_profiles (
      user_id,
      username,
      full_name,
      email,
      phone_number,
      gender,
      date_of_birth,
      specialization,
      current_hospital,
      created_at,
      updated_at,
      sync_status
    ) values (
      new.id,
      v_username,
      v_full_name,
      new.email,
      v_phone,
      v_gender,
      v_date_of_birth,
      coalesce(v_specialization, 'General'),
      coalesce(v_current_hospital, 'Unknown'),
      now(),
      now(),
      'synced'
    )
    on conflict (user_id) do update set
      username = excluded.username,
      full_name = excluded.full_name,
      email = excluded.email,
      phone_number = excluded.phone_number,
      gender = excluded.gender,
      date_of_birth = excluded.date_of_birth,
      specialization = excluded.specialization,
      current_hospital = excluded.current_hospital,
      updated_at = now();
  else
    insert into public.patient_records (
      user_id,
      username,
      full_name,
      email,
      phone_number,
      gender,
      date_of_birth,
      location,
      created_at,
      updated_at,
      sync_status
    ) values (
      new.id,
      v_username,
      v_full_name,
      new.email,
      coalesce(v_phone, ''),
      v_gender,
      v_date_of_birth,
      v_location,
      now(),
      now(),
      'synced'
    )
    on conflict (user_id) do update set
      username = excluded.username,
      full_name = excluded.full_name,
      email = excluded.email,
      phone_number = excluded.phone_number,
      gender = excluded.gender,
      date_of_birth = excluded.date_of_birth,
      location = excluded.location,
      updated_at = now();
  end if;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_user_profile();

-- Optional: backfill existing users once after enabling trigger.
-- insert into public.patient_records (...) select ... from auth.users;

