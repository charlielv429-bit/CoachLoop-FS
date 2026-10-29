CREATE SCHEMA teaching;
REVOKE ALL ON SCHEMA teaching FROM PUBLIC;
DO $roles$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['teaching_agent','teaching_teacher','teaching_coach','teaching_reader'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',r);
    ELSIF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=r AND
       (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN
      RAISE EXCEPTION 'unsafe existing teaching group role';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles p ON p.oid=m.member WHERE p.rolname=r) THEN
      RAISE EXCEPTION 'teaching group must not inherit other roles';
    END IF;
  END LOOP;
END $roles$;

CREATE FUNCTION teaching.valid_plan_payload(p jsonb, prep int, main int, closing int,
                                           grp numeric, indiv numeric, hr numeric, kind text)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $body$
DECLARE k text; ph jsonb;
BEGIN
  IF jsonb_typeof(p) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
  FOREACH k IN ARRAY ARRAY['guiding_ideology','teaching_material_analysis','learner_analysis',
     'venue_equipment','safety_precautions','teaching_flow','load_accounting'] LOOP
    IF jsonb_typeof(p->k) IS DISTINCT FROM 'object' OR p->k = '{}'::jsonb THEN RETURN false; END IF;
  END LOOP;
  IF p->>'schema_version' IS DISTINCT FROM 'db-a-1' THEN RETURN false; END IF;
  ph := p->'teaching_flow';
  RETURN COALESCE((ph->>'total_minutes')::int=45 AND
      (ph->>'prep_minutes')::int=prep AND (ph->>'main_minutes')::int=main AND
      (ph->>'closing_minutes')::int=closing AND
      (p->'load_accounting'->>'total_minutes')::int=45 AND
      (p->'load_accounting'->>'group_active_minutes')::numeric=grp AND
      (p->'load_accounting'->>'individual_active_minutes')::numeric=indiv AND
      (p->'load_accounting'->>'avg_hr')::numeric=hr AND
      p->'load_accounting'->>'kind'=kind, false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $body$;
