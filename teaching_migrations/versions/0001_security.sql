-- Tenant identity is bound to an administrator-provisioned LOGIN role, never a GUC
-- supplied by an Agent. SET ROLE cannot change session_user.
CREATE FUNCTION teaching.current_tenant() RETURNS uuid LANGUAGE sql STABLE
SET search_path=pg_catalog AS $$
 SELECT ((regexp_match(session_user::text,
   '^tdb_([0-9a-f]{32})_(agent|teacher|coach|reader)$'))[1])::uuid
$$;

CREATE FUNCTION teaching.stamp_record() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,teaching AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    NEW.created_by := session_user;
    NEW.created_at := clock_timestamp();
  END IF;
  NEW.updated_at := clock_timestamp();
  RETURN NEW;
END $$;

CREATE FUNCTION teaching.deny_history_mutation() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'event snapshots and coach reviews are append-only' USING ERRCODE='42501'; END $$;

CREATE FUNCTION teaching.protect_plan() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog AS $$
DECLARE mutable text[] := ARRAY['review_status','reviewed_by','reviewed_at','review_history','updated_at','group_density','individual_density'];
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'plan versions cannot be deleted' USING ERRCODE='42501'; END IF;
  IF (to_jsonb(NEW)-mutable) IS DISTINCT FROM (to_jsonb(OLD)-mutable) THEN
    RAISE EXCEPTION 'plan content is immutable; create a new version' USING ERRCODE='42501';
  END IF;
  IF jsonb_array_length(NEW.review_history) <> jsonb_array_length(OLD.review_history)+1 OR
     NEW.review_history - (jsonb_array_length(NEW.review_history)-1) <> OLD.review_history THEN
    RAISE EXCEPTION 'plan review history must append exactly one action' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;

DO $policies$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['classes','lessons','lesson_plans','training_sessions','pose_events','coach_reviews'] LOOP
    EXECUTE format('ALTER TABLE teaching.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE teaching.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY tenant_mock ON teaching.%I USING (tenant_id=teaching.current_tenant() AND data_domain=''mock'') WITH CHECK (tenant_id=teaching.current_tenant() AND data_domain=''mock'')',t);
    EXECUTE format('CREATE TRIGGER stamp BEFORE INSERT OR UPDATE ON teaching.%I FOR EACH ROW EXECUTE FUNCTION teaching.stamp_record()',t);
  END LOOP;
END $policies$;
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON teaching.pose_events FOR EACH ROW EXECUTE FUNCTION teaching.deny_history_mutation();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON teaching.coach_reviews FOR EACH ROW EXECUTE FUNCTION teaching.deny_history_mutation();
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON teaching.lesson_plans FOR EACH ROW EXECUTE FUNCTION teaching.protect_plan();

CREATE FUNCTION teaching.create_draft(lesson uuid, p jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,teaching AS $$
DECLARE own uuid := teaching.current_tenant(); new_id uuid; version int;
BEGIN
  IF own IS NULL OR NOT (pg_has_role(session_user,'teaching_agent','member') OR
       pg_has_role(session_user,'teaching_teacher','member')) THEN
    RAISE EXCEPTION 'draft author role required' USING ERRCODE='42501';
  END IF;
  PERFORM 1 FROM teaching.lessons WHERE id=lesson AND tenant_id=own AND data_domain='mock' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'lesson unavailable' USING ERRCODE='42501'; END IF;
  SELECT COALESCE(max(version_no),0)+1 INTO version FROM teaching.lesson_plans
     WHERE lesson_id=lesson AND tenant_id=own AND data_domain='mock';
  INSERT INTO teaching.lesson_plans(tenant_id,lesson_id,version_no,payload,source_kind,
      prep_minutes,main_minutes,closing_minutes,load_total_minutes,
      group_active_minutes,individual_active_minutes,avg_hr,measurement_kind)
  VALUES(own,lesson,version,p,CASE WHEN pg_has_role(session_user,'teaching_agent','member') THEN 'agent' ELSE 'manual' END,
      (p->'teaching_flow'->>'prep_minutes')::int,(p->'teaching_flow'->>'main_minutes')::int,
      (p->'teaching_flow'->>'closing_minutes')::int,(p->'load_accounting'->>'total_minutes')::int,
      (p->'load_accounting'->>'group_active_minutes')::numeric,
      (p->'load_accounting'->>'individual_active_minutes')::numeric,
      (p->'load_accounting'->>'avg_hr')::numeric,p->'load_accounting'->>'kind') RETURNING id INTO new_id;
  RETURN new_id;
END $$;

CREATE FUNCTION teaching.review_plan(plan uuid, new_status text, expected_seq int, note text DEFAULT '') RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,teaching AS $$
DECLARE own uuid := teaching.current_tenant(); old teaching.lesson_plans%ROWTYPE; human boolean;
BEGIN
  human := pg_has_role(session_user,'teaching_teacher','member');
  IF own IS NULL OR NOT (human OR pg_has_role(session_user,'teaching_agent','member')) THEN
    RAISE EXCEPTION 'review role required' USING ERRCODE='42501'; END IF;
  IF new_status IS NULL OR note IS NULL OR new_status NOT IN ('pending','approved','needs_revision') OR length(note)>1000 THEN
    RAISE EXCEPTION 'invalid plan action' USING ERRCODE='23514'; END IF;
  IF new_status <> 'pending' AND NOT human THEN
    RAISE EXCEPTION 'teacher approval requires teacher login' USING ERRCODE='42501'; END IF;
  SELECT * INTO old FROM teaching.lesson_plans WHERE id=plan AND tenant_id=own AND data_domain='mock' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'plan unavailable' USING ERRCODE='42501'; END IF;
  IF expected_seq IS NULL OR jsonb_array_length(old.review_history) <> expected_seq THEN
    RAISE EXCEPTION 'stale plan revision' USING ERRCODE='40001'; END IF;
  IF (new_status='pending' AND old.review_status<>'draft') OR
     (new_status<>'pending' AND old.review_status<>'pending') THEN
    RAISE EXCEPTION 'invalid plan transition' USING ERRCODE='23514'; END IF;
  UPDATE teaching.lesson_plans SET review_status=new_status,
      reviewed_by=CASE WHEN new_status='pending' THEN NULL ELSE session_user END,
      reviewed_at=CASE WHEN new_status='pending' THEN NULL ELSE clock_timestamp() END,
      review_history=old.review_history || jsonb_build_array(jsonb_build_object(
          'seq',expected_seq+1,'from',old.review_status,'to',new_status,
          'actor',session_user,'at',clock_timestamp(),'note',note)) WHERE id=old.id;
END $$;

CREATE FUNCTION teaching.review_event(event uuid, new_status text, expected_seq int, request_key uuid, note text DEFAULT '') RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,teaching AS $$
DECLARE own uuid := teaching.current_tenant(); last_seq int; new_id uuid; existing teaching.coach_reviews%ROWTYPE;
BEGIN
  IF own IS NULL OR NOT pg_has_role(session_user,'teaching_coach','member') THEN
    RAISE EXCEPTION 'authenticated coach login required' USING ERRCODE='42501'; END IF;
  IF new_status IS NULL OR new_status NOT IN ('pending','confirmed','normal_movement','tracking_error','uncertain')
       OR note IS NULL OR length(note)>1000 OR request_key IS NULL THEN
    RAISE EXCEPTION 'invalid review action' USING ERRCODE='23514'; END IF;
  PERFORM 1 FROM teaching.pose_events WHERE id=event AND tenant_id=own AND data_domain='mock' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'event unavailable' USING ERRCODE='42501'; END IF;
  SELECT * INTO existing FROM teaching.coach_reviews WHERE tenant_id=own AND data_domain='mock' AND idempotency_key=request_key;
  IF FOUND THEN
    IF existing.pose_event_id=event AND existing.status=new_status AND existing.note=note AND existing.reviewer_id=session_user THEN
      RETURN existing.id;
    END IF;
    RAISE EXCEPTION 'idempotency key reused for a different request' USING ERRCODE='23505';
  END IF;
  SELECT COALESCE(max(review_seq),0) INTO last_seq FROM teaching.coach_reviews WHERE pose_event_id=event AND tenant_id=own AND data_domain='mock';
  IF expected_seq IS NULL OR expected_seq<>last_seq THEN
    RAISE EXCEPTION 'stale event revision' USING ERRCODE='40001'; END IF;
  INSERT INTO teaching.coach_reviews(tenant_id,pose_event_id,review_seq,status,reviewer_id,note,idempotency_key,source_kind)
     VALUES(own,event,last_seq+1,new_status,session_user,note,request_key,'manual') RETURNING id INTO new_id;
  RETURN new_id;
END $$;

CREATE VIEW teaching.event_review_state WITH (security_invoker=true) AS
 SELECT e.id,e.tenant_id,e.data_domain,COALESCE(r.status,'pending') AS review_status,
        r.review_seq,r.reviewer_id,r.reviewed_at
 FROM teaching.pose_events e LEFT JOIN LATERAL (
   SELECT status,review_seq,reviewer_id,reviewed_at FROM teaching.coach_reviews c
   WHERE c.pose_event_id=e.id AND c.tenant_id=e.tenant_id AND c.data_domain=e.data_domain
   ORDER BY review_seq DESC LIMIT 1
 ) r ON true;
COMMENT ON VIEW teaching.event_review_state IS 'confirmed means observable movement change, never an automatic technical error';

REVOKE ALL ON ALL TABLES IN SCHEMA teaching FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA teaching FROM PUBLIC;
GRANT USAGE ON SCHEMA teaching TO teaching_agent,teaching_teacher,teaching_coach,teaching_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA teaching TO teaching_agent,teaching_teacher,teaching_coach,teaching_reader;
GRANT EXECUTE ON FUNCTION teaching.current_tenant() TO teaching_agent,teaching_teacher,teaching_coach,teaching_reader;
GRANT INSERT ON teaching.classes,teaching.lessons,teaching.training_sessions,teaching.pose_events TO teaching_teacher;
GRANT EXECUTE ON FUNCTION teaching.create_draft(uuid,jsonb) TO teaching_agent,teaching_teacher;
GRANT EXECUTE ON FUNCTION teaching.review_plan(uuid,text,int,text) TO teaching_agent,teaching_teacher;
GRANT EXECUTE ON FUNCTION teaching.review_event(uuid,text,int,uuid,text) TO teaching_coach;
