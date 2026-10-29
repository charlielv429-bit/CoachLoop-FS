CREATE SCHEMA teaching_ingest;
REVOKE ALL ON SCHEMA teaching_ingest FROM PUBLIC;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='teaching_importer') THEN
  CREATE ROLE teaching_importer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
 ELSIF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='teaching_importer' AND
     (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) OR
     EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='teaching_importer') THEN
  RAISE EXCEPTION 'unsafe existing importer role';
 END IF;
END $$;
CREATE OR REPLACE FUNCTION teaching.current_tenant() RETURNS uuid LANGUAGE sql STABLE
 SET search_path=pg_catalog AS $$ SELECT ((regexp_match(session_user::text,
 '^tdb_([0-9a-f]{32})_(agent|teacher|coach|reader|importer)$'))[1])::uuid $$;

-- Only a trusted fixture administrator may register exact, known synthetic inputs.
-- No business-role INSERT/UPDATE/DELETE or public HTTP registration endpoint exists.
CREATE TABLE teaching_ingest.mock_artifacts (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, data_domain varchar(8) NOT NULL DEFAULT 'mock' CHECK(data_domain='mock'),
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object' AND payload->>'data_domain'='mock'
    AND payload->'source'->>'kind'='synthetic' AND payload->'source'->'is_mock'='true'::jsonb),
 created_by text NOT NULL DEFAULT session_user, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(tenant_id,data_domain,id)
);
CREATE TABLE teaching_ingest.receipts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
 data_domain varchar(8) NOT NULL DEFAULT 'mock' CHECK(data_domain='mock'),
 artifact_id uuid NOT NULL, idempotency_key uuid NOT NULL,
 class_id uuid NOT NULL, lesson_id uuid NOT NULL, training_session_id uuid NOT NULL, analysis_run_id uuid NOT NULL,
 event_map jsonb NOT NULL CHECK(jsonb_typeof(event_map)='array'),
 created_by text NOT NULL DEFAULT session_user, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(tenant_id,data_domain,id), UNIQUE(tenant_id,data_domain,idempotency_key),
 FOREIGN KEY(tenant_id,data_domain,artifact_id) REFERENCES teaching_ingest.mock_artifacts(tenant_id,data_domain,id),
 FOREIGN KEY(tenant_id,data_domain,training_session_id) REFERENCES teaching.training_sessions(tenant_id,data_domain,id),
 FOREIGN KEY(tenant_id,data_domain,lesson_id) REFERENCES teaching.lessons(tenant_id,data_domain,id),
 FOREIGN KEY(tenant_id,data_domain,class_id) REFERENCES teaching.classes(tenant_id,data_domain,id)
);
CREATE INDEX ix_receipts_session ON teaching_ingest.receipts(tenant_id,data_domain,training_session_id,analysis_run_id);
CREATE TABLE teaching_ingest.review_claims (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
 data_domain varchar(8) NOT NULL DEFAULT 'mock' CHECK(data_domain='mock'),
 receipt_id uuid NOT NULL, pose_event_id uuid NOT NULL, source_stream_id uuid NOT NULL,
 source_sequence int NOT NULL CHECK(source_sequence BETWEEN 1 AND 100),
 source_status varchar(20) NOT NULL CHECK(source_status IN ('pending','confirmed','normal_movement','tracking_error','uncertain')),
 source_reviewed_by varchar(53) NOT NULL CHECK(source_reviewed_by ~ '^MOCK-[A-Z0-9_-]{1,48}$'),
 source_reviewed_at timestamptz NOT NULL, source_note text NOT NULL CHECK(length(source_note)<=1000),
 verification_status text NOT NULL DEFAULT 'imported_unverified' CHECK(verification_status='imported_unverified'),
 text_status text NOT NULL DEFAULT 'quarantined' CHECK(text_status='quarantined'),
 created_by text NOT NULL DEFAULT session_user, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(tenant_id,data_domain,pose_event_id,source_stream_id,source_sequence),
 FOREIGN KEY(tenant_id,data_domain,receipt_id) REFERENCES teaching_ingest.receipts(tenant_id,data_domain,id),
 FOREIGN KEY(tenant_id,data_domain,pose_event_id) REFERENCES teaching.pose_events(tenant_id,data_domain,id)
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['mock_artifacts','receipts','review_claims'] LOOP
  EXECUTE format('ALTER TABLE teaching_ingest.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE teaching_ingest.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_mock ON teaching_ingest.%I USING(tenant_id=teaching.current_tenant() AND data_domain=''mock'') WITH CHECK(tenant_id=teaching.current_tenant() AND data_domain=''mock'')',t);
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON teaching_ingest.%I FOR EACH ROW EXECUTE FUNCTION teaching.deny_history_mutation()',t);
 END LOOP;
END $$;

CREATE FUNCTION teaching_ingest.import_results(request_key uuid, p jsonb) RETURNS TABLE(receipt_id uuid,replayed boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,teaching,teaching_ingest AS $$
DECLARE own uuid:=teaching.current_tenant(); artifact teaching_ingest.mock_artifacts%ROWTYPE;
 old_receipt teaching_ingest.receipts%ROWTYPE; e jsonb; h jsonb; existing teaching.pose_events%ROWTYPE;
 existing_claim teaching_ingest.review_claims%ROWTYPE; eid uuid; rid uuid:=gen_random_uuid();
 mappings jsonb:='[]'; i int; last_sequence int; source_stream uuid;
BEGIN
 IF own IS NULL OR NOT pg_has_role(session_user,'teaching_importer','member') THEN
  RAISE EXCEPTION 'importer login required' USING ERRCODE='42501'; END IF;
 IF request_key IS NULL OR p->>'data_domain' IS DISTINCT FROM 'mock' OR
    p->>'schema_version' IS DISTINCT FROM 'reviewed-training-import-v1' OR p->>'time_unit' IS DISTINCT FROM 'ms' OR
    p->'source'->>'kind' IS DISTINCT FROM 'synthetic' OR p->'source'->'is_mock' IS DISTINCT FROM 'true'::jsonb THEN
  RAISE EXCEPTION 'mock contract required' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM teaching.training_sessions s JOIN teaching.lessons l ON l.id=s.lesson_id
   AND l.tenant_id=s.tenant_id AND l.data_domain=s.data_domain
   WHERE s.tenant_id=own AND s.data_domain='mock' AND s.id=(p->>'training_session_id')::uuid
   AND s.lesson_id=(p->>'lesson_id')::uuid AND l.class_id=(p->>'class_id')::uuid FOR UPDATE OF s;
 IF NOT FOUND THEN RAISE EXCEPTION 'session unavailable' USING ERRCODE='P0002'; END IF;
 SELECT * INTO artifact FROM teaching_ingest.mock_artifacts WHERE tenant_id=own AND data_domain='mock'
    AND id=(p->'source'->>'artifact_id')::uuid;
 IF NOT FOUND OR artifact.payload IS DISTINCT FROM p THEN
  RAISE EXCEPTION 'unregistered synthetic artifact' USING ERRCODE='42501'; END IF;
 SELECT * INTO old_receipt FROM teaching_ingest.receipts WHERE tenant_id=own AND data_domain='mock' AND idempotency_key=request_key;
 IF FOUND THEN
  IF old_receipt.artifact_id=artifact.id THEN RETURN QUERY SELECT old_receipt.id,true; RETURN; END IF;
  RAISE EXCEPTION 'idempotency key conflict' USING ERRCODE='23505';
 END IF;
 IF jsonb_typeof(p->'events') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'events') NOT BETWEEN 1 AND 100 THEN
  RAISE EXCEPTION 'invalid events' USING ERRCODE='23514'; END IF;
 source_stream:=(p->'source'->>'source_stream_id')::uuid;
 FOR e IN SELECT value FROM jsonb_array_elements(p->'events') LOOP
  IF e->>'event_id' IS NULL OR e->>'event_id' !~ '^evt_[0-9a-f]{12}$' THEN RAISE EXCEPTION 'invalid source event id' USING ERRCODE='23514'; END IF;
  SELECT * INTO existing FROM teaching.pose_events WHERE tenant_id=own AND data_domain='mock'
   AND training_session_id=(p->>'training_session_id')::uuid AND analysis_run_id=(p->>'analysis_run_id')::uuid
   AND ((feature=e->>'feature' AND frame_start=(e->>'frame_start')::int AND frame_end=(e->>'frame_end')::int)
        OR legacy_event_id=e->>'event_id') LIMIT 1;
  IF FOUND THEN
   IF existing.legacy_event_id IS DISTINCT FROM e->>'event_id' OR existing.feature IS DISTINCT FROM e->>'feature' OR
      existing.frame_start IS DISTINCT FROM (e->>'frame_start')::int OR existing.frame_end IS DISTINCT FROM (e->>'frame_end')::int OR
      existing.start_time_ms IS DISTINCT FROM (e->>'start_time_ms')::numeric OR existing.end_time_ms IS DISTINCT FROM (e->>'end_time_ms')::numeric OR
      existing.deviation_max IS DISTINCT FROM (e->>'deviation_max')::numeric OR existing.original_event IS DISTINCT FROM e->'original_event' THEN
    RAISE EXCEPTION 'event conflict' USING ERRCODE='23505'; END IF;
   eid:=existing.id;
  ELSE
   INSERT INTO teaching.pose_events(tenant_id,training_session_id,analysis_run_id,legacy_event_id,feature,frame_start,frame_end,
      start_time_ms,end_time_ms,deviation_max,original_event,source_snapshot,source_kind)
    VALUES(own,(p->>'training_session_id')::uuid,(p->>'analysis_run_id')::uuid,e->>'event_id',e->>'feature',
      (e->>'frame_start')::int,(e->>'frame_end')::int,(e->>'start_time_ms')::numeric,(e->>'end_time_ms')::numeric,
      (e->>'deviation_max')::numeric,e->'original_event',jsonb_build_object('is_mock',true,'source','mock://integration/'||artifact.id::text),'mock_import')
    RETURNING id INTO eid;
  END IF;
  mappings:=mappings||jsonb_build_array(jsonb_build_object('event_id',eid,'source_event_id',e->>'event_id'));
 END LOOP;
 INSERT INTO teaching_ingest.receipts(id,tenant_id,artifact_id,idempotency_key,class_id,lesson_id,training_session_id,analysis_run_id,event_map)
  VALUES(rid,own,artifact.id,request_key,(p->>'class_id')::uuid,(p->>'lesson_id')::uuid,(p->>'training_session_id')::uuid,(p->>'analysis_run_id')::uuid,mappings);
 i:=0;
 FOR e IN SELECT value FROM jsonb_array_elements(p->'events') LOOP
  eid:=(mappings->i->>'event_id')::uuid; i:=i+1; last_sequence:=0;
  IF jsonb_typeof(e->'review'->'review_history') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'invalid history' USING ERRCODE='23514'; END IF;
  FOR h IN SELECT value FROM jsonb_array_elements(e->'review'->'review_history') LOOP
   last_sequence:=last_sequence+1;
   IF (h->>'sequence')::int IS DISTINCT FROM last_sequence THEN RAISE EXCEPTION 'history sequence gap' USING ERRCODE='23514'; END IF;
   SELECT * INTO existing_claim FROM teaching_ingest.review_claims WHERE tenant_id=own AND data_domain='mock'
    AND pose_event_id=eid AND source_stream_id=source_stream AND source_sequence=last_sequence;
   IF FOUND THEN
    IF existing_claim.source_status IS DISTINCT FROM h->>'status' OR existing_claim.source_reviewed_by IS DISTINCT FROM h->>'reviewed_by' OR
       existing_claim.source_reviewed_at IS DISTINCT FROM (h->>'reviewed_at')::timestamptz OR existing_claim.source_note IS DISTINCT FROM h->>'note' THEN
     RAISE EXCEPTION 'source history conflict' USING ERRCODE='23505'; END IF;
   ELSE
    INSERT INTO teaching_ingest.review_claims(tenant_id,receipt_id,pose_event_id,source_stream_id,source_sequence,source_status,source_reviewed_by,source_reviewed_at,source_note)
      VALUES(own,rid,eid,source_stream,last_sequence,h->>'status',h->>'reviewed_by',(h->>'reviewed_at')::timestamptz,h->>'note');
   END IF;
  END LOOP;
  IF last_sequence < (SELECT COALESCE(max(source_sequence),0) FROM teaching_ingest.review_claims
      WHERE tenant_id=own AND data_domain='mock' AND pose_event_id=eid AND source_stream_id=source_stream) THEN
   RAISE EXCEPTION 'source history truncated' USING ERRCODE='23505'; END IF;
  IF (last_sequence=0 AND e->'review'->>'review_status' IS DISTINCT FROM 'pending') OR
     (last_sequence>0 AND e->'review'->>'review_status' IS DISTINCT FROM h->>'status') THEN
   RAISE EXCEPTION 'source review status mismatch' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN QUERY SELECT rid,false;
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA teaching_ingest FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA teaching_ingest FROM PUBLIC;
GRANT USAGE ON SCHEMA teaching,teaching_ingest TO teaching_importer;
GRANT EXECUTE ON FUNCTION teaching.current_tenant() TO teaching_importer;
GRANT SELECT ON teaching.classes,teaching.lessons,teaching.training_sessions,teaching.pose_events,teaching.coach_reviews,teaching.event_review_state TO teaching_importer;
GRANT SELECT ON teaching_ingest.receipts TO teaching_importer,teaching_teacher,teaching_coach,teaching_reader;
GRANT SELECT ON teaching_ingest.review_claims TO teaching_teacher,teaching_coach;
GRANT SELECT(id,tenant_id,data_domain,receipt_id,pose_event_id,source_stream_id,source_sequence,source_status,verification_status,text_status,created_at)
 ON teaching_ingest.review_claims TO teaching_importer,teaching_reader;
GRANT USAGE ON SCHEMA teaching_ingest TO teaching_teacher,teaching_coach,teaching_reader;
GRANT EXECUTE ON FUNCTION teaching_ingest.import_results(uuid,jsonb) TO teaching_importer;
