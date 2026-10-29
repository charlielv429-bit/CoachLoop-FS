-- Frozen DB-A table/index DDL. Changes require a new revision.


CREATE TABLE teaching.classes (
	class_code VARCHAR(32) NOT NULL,
	display_name VARCHAR(80) NOT NULL,
	student_count INTEGER NOT NULL,
	status VARCHAR(16) DEFAULT 'draft' NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID NOT NULL,
	data_domain VARCHAR(8) DEFAULT 'mock' NOT NULL,
	source_kind VARCHAR(24) DEFAULT 'mock_import' NOT NULL,
	source_ref TEXT,
	source_schema_version VARCHAR(16) DEFAULT 'db-a-1' NOT NULL,
	created_by TEXT DEFAULT session_user NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (tenant_id, data_domain, id),
	CONSTRAINT ck_mock_only CHECK (data_domain = 'mock'),
	CONSTRAINT ck_source CHECK (source_kind IN ('manual','agent','mock_import','v4_import','v5_import')),
	UNIQUE (tenant_id, data_domain, class_code),
	CONSTRAINT ck_count CHECK (student_count > 0),
	CONSTRAINT ck_status CHECK (status IN ('draft','active','archived'))
)

;


CREATE TABLE teaching.lessons (
	class_id UUID NOT NULL,
	lesson_code VARCHAR(32) NOT NULL,
	theme_code VARCHAR(64) DEFAULT 'beginner_two_foot_glide_posture' NOT NULL,
	skill_level VARCHAR(16) DEFAULT 'beginner' NOT NULL,
	total_minutes INTEGER DEFAULT '45' NOT NULL,
	status VARCHAR(16) DEFAULT 'draft' NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID NOT NULL,
	data_domain VARCHAR(8) DEFAULT 'mock' NOT NULL,
	source_kind VARCHAR(24) DEFAULT 'mock_import' NOT NULL,
	source_ref TEXT,
	source_schema_version VARCHAR(16) DEFAULT 'db-a-1' NOT NULL,
	created_by TEXT DEFAULT session_user NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (tenant_id, data_domain, id),
	CONSTRAINT ck_mock_only CHECK (data_domain = 'mock'),
	CONSTRAINT ck_source CHECK (source_kind IN ('manual','agent','mock_import','v4_import','v5_import')),
	FOREIGN KEY(tenant_id, data_domain, class_id) REFERENCES teaching.classes (tenant_id, data_domain, id) ON DELETE RESTRICT,
	UNIQUE (tenant_id, data_domain, class_id, lesson_code),
	CONSTRAINT ck_time CHECK (total_minutes = 45),
	CONSTRAINT ck_template CHECK (theme_code = 'beginner_two_foot_glide_posture' AND skill_level = 'beginner'),
	CONSTRAINT ck_status CHECK (status IN ('draft','scheduled','completed','cancelled'))
)

;


CREATE TABLE teaching.lesson_plans (
	lesson_id UUID NOT NULL,
	version_no INTEGER NOT NULL,
	payload JSONB NOT NULL,
	total_minutes INTEGER DEFAULT '45' NOT NULL,
	prep_minutes INTEGER NOT NULL,
	main_minutes INTEGER NOT NULL,
	closing_minutes INTEGER NOT NULL,
	load_total_minutes INTEGER NOT NULL,
	group_active_minutes NUMERIC NOT NULL,
	individual_active_minutes NUMERIC NOT NULL,
	avg_hr NUMERIC NOT NULL,
	measurement_kind VARCHAR(16) DEFAULT 'estimated' NOT NULL,
	group_density NUMERIC GENERATED ALWAYS AS (group_active_minutes / total_minutes * 100) STORED NOT NULL,
	individual_density NUMERIC GENERATED ALWAYS AS (individual_active_minutes / total_minutes * 100) STORED NOT NULL,
	review_status VARCHAR(20) DEFAULT 'draft' NOT NULL,
	reviewed_by TEXT,
	reviewed_at TIMESTAMP WITH TIME ZONE,
	review_history JSONB DEFAULT '[]'::jsonb NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID NOT NULL,
	data_domain VARCHAR(8) DEFAULT 'mock' NOT NULL,
	source_kind VARCHAR(24) DEFAULT 'mock_import' NOT NULL,
	source_ref TEXT,
	source_schema_version VARCHAR(16) DEFAULT 'db-a-1' NOT NULL,
	created_by TEXT DEFAULT session_user NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (tenant_id, data_domain, id),
	CONSTRAINT ck_mock_only CHECK (data_domain = 'mock'),
	CONSTRAINT ck_source CHECK (source_kind IN ('manual','agent','mock_import','v4_import','v5_import')),
	FOREIGN KEY(tenant_id, data_domain, lesson_id) REFERENCES teaching.lessons (tenant_id, data_domain, id) ON DELETE RESTRICT,
	UNIQUE (tenant_id, data_domain, lesson_id, version_no),
	CONSTRAINT uq_plan_lesson UNIQUE (tenant_id, data_domain, lesson_id, id),
	CONSTRAINT ck_version CHECK (version_no > 0),
	CONSTRAINT ck_time CHECK (total_minutes = 45 AND load_total_minutes = total_minutes AND prep_minutes BETWEEN 8 AND 10 AND main_minutes BETWEEN 28 AND 30 AND closing_minutes BETWEEN 5 AND 7 AND prep_minutes + main_minutes + closing_minutes = total_minutes),
	CONSTRAINT ck_load CHECK (group_active_minutes BETWEEN 0 AND total_minutes AND individual_active_minutes BETWEEN 0 AND total_minutes AND avg_hr BETWEEN 20 AND 250),
	CONSTRAINT ck_kind CHECK (measurement_kind IN ('estimated','measured')),
	CONSTRAINT ck_review CHECK (review_status IN ('draft','pending','approved','needs_revision')),
	CONSTRAINT ck_history CHECK (jsonb_typeof(review_history) = 'array'),
	CONSTRAINT ck_reviewer CHECK ((review_status IN ('approved','needs_revision') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL) OR (review_status IN ('draft','pending') AND reviewed_by IS NULL AND reviewed_at IS NULL)),
	CONSTRAINT ck_payload CHECK (teaching.valid_plan_payload(payload, prep_minutes, main_minutes, closing_minutes, group_active_minutes, individual_active_minutes, avg_hr, measurement_kind))
)

;

CREATE INDEX ix_plans_review ON teaching.lesson_plans (tenant_id, data_domain, review_status);


CREATE TABLE teaching.training_sessions (
	lesson_id UUID NOT NULL,
	lesson_plan_id UUID,
	session_code VARCHAR(40) NOT NULL,
	participant_code VARCHAR(32) NOT NULL,
	status VARCHAR(16) DEFAULT 'planned' NOT NULL,
	video_object_key TEXT,
	features_object_key TEXT,
	analysis_metadata JSONB DEFAULT '{}'::jsonb NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID NOT NULL,
	data_domain VARCHAR(8) DEFAULT 'mock' NOT NULL,
	source_kind VARCHAR(24) DEFAULT 'mock_import' NOT NULL,
	source_ref TEXT,
	source_schema_version VARCHAR(16) DEFAULT 'db-a-1' NOT NULL,
	created_by TEXT DEFAULT session_user NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (tenant_id, data_domain, id),
	CONSTRAINT ck_mock_only CHECK (data_domain = 'mock'),
	CONSTRAINT ck_source CHECK (source_kind IN ('manual','agent','mock_import','v4_import','v5_import')),
	FOREIGN KEY(tenant_id, data_domain, lesson_id) REFERENCES teaching.lessons (tenant_id, data_domain, id) ON DELETE RESTRICT,
	FOREIGN KEY(tenant_id, data_domain, lesson_id, lesson_plan_id) REFERENCES teaching.lesson_plans (tenant_id, data_domain, lesson_id, id) ON DELETE RESTRICT,
	UNIQUE (tenant_id, data_domain, session_code),
	CONSTRAINT ck_status CHECK (status IN ('planned','completed','cancelled')),
	CONSTRAINT ck_anonymous CHECK (participant_code ~ '^MOCK-[A-Z0-9_-]+$'),
	CONSTRAINT ck_mock_assets CHECK ((video_object_key IS NULL OR video_object_key LIKE 'mock://videos/%%') AND (features_object_key IS NULL OR features_object_key LIKE 'mock://features/%%'))
)

;

CREATE INDEX ix_sessions_lesson ON teaching.training_sessions (tenant_id, data_domain, lesson_id);


CREATE TABLE teaching.pose_events (
	training_session_id UUID NOT NULL,
	analysis_run_id UUID NOT NULL,
	legacy_event_id VARCHAR(16),
	feature VARCHAR(32) NOT NULL,
	frame_start INTEGER NOT NULL,
	frame_end INTEGER NOT NULL,
	start_time_ms NUMERIC NOT NULL,
	end_time_ms NUMERIC NOT NULL,
	deviation_max NUMERIC NOT NULL,
	original_event JSONB NOT NULL,
	source_snapshot JSONB NOT NULL,
	quality_status VARCHAR(16) DEFAULT 'candidate' NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID NOT NULL,
	data_domain VARCHAR(8) DEFAULT 'mock' NOT NULL,
	source_kind VARCHAR(24) DEFAULT 'mock_import' NOT NULL,
	source_ref TEXT,
	source_schema_version VARCHAR(16) DEFAULT 'db-a-1' NOT NULL,
	created_by TEXT DEFAULT session_user NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (tenant_id, data_domain, id),
	CONSTRAINT ck_mock_only CHECK (data_domain = 'mock'),
	CONSTRAINT ck_source CHECK (source_kind IN ('manual','agent','mock_import','v4_import','v5_import')),
	FOREIGN KEY(tenant_id, data_domain, training_session_id) REFERENCES teaching.training_sessions (tenant_id, data_domain, id) ON DELETE RESTRICT,
	UNIQUE (tenant_id, data_domain, training_session_id, analysis_run_id, feature, frame_start, frame_end),
	UNIQUE (tenant_id, data_domain, training_session_id, analysis_run_id, legacy_event_id),
	CONSTRAINT ck_legacy_id CHECK (legacy_event_id IS NULL OR legacy_event_id ~ '^evt_[0-9a-f]{12}$'),
	CONSTRAINT ck_feature CHECK (feature IN ('knee_angle_deg','torso_pitch_deg','hip_ankle_offset_norm')),
	CONSTRAINT ck_geometry CHECK (frame_start >= 0 AND frame_end >= frame_start AND start_time_ms >= 0 AND end_time_ms >= start_time_ms AND end_time_ms < 'Infinity'::numeric AND deviation_max >= 0 AND deviation_max < 'Infinity'::numeric),
	CONSTRAINT ck_quality CHECK (quality_status IN ('candidate','quarantined')),
	CONSTRAINT ck_snapshots CHECK (jsonb_typeof(original_event) = 'object' AND jsonb_typeof(source_snapshot) = 'object'),
	CONSTRAINT ck_mock_snapshot CHECK (COALESCE(source_snapshot->'is_mock' = 'true'::jsonb AND source_snapshot->>'source' LIKE 'mock://%%', false)),
	CONSTRAINT ck_event_snapshot CHECK (COALESCE(original_event->>'feature' = feature AND (original_event->>'frame_start')::int = frame_start AND (original_event->>'frame_end')::int = frame_end, false))
)

;

CREATE INDEX ix_events_time ON teaching.pose_events (tenant_id, data_domain, training_session_id, frame_start);


CREATE TABLE teaching.coach_reviews (
	pose_event_id UUID NOT NULL,
	review_seq INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	reviewer_id TEXT NOT NULL,
	reviewed_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	note TEXT DEFAULT '' NOT NULL,
	idempotency_key UUID NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	tenant_id UUID NOT NULL,
	data_domain VARCHAR(8) DEFAULT 'mock' NOT NULL,
	source_kind VARCHAR(24) DEFAULT 'mock_import' NOT NULL,
	source_ref TEXT,
	source_schema_version VARCHAR(16) DEFAULT 'db-a-1' NOT NULL,
	created_by TEXT DEFAULT session_user NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (tenant_id, data_domain, id),
	CONSTRAINT ck_mock_only CHECK (data_domain = 'mock'),
	CONSTRAINT ck_source CHECK (source_kind IN ('manual','agent','mock_import','v4_import','v5_import')),
	FOREIGN KEY(tenant_id, data_domain, pose_event_id) REFERENCES teaching.pose_events (tenant_id, data_domain, id) ON DELETE RESTRICT,
	UNIQUE (tenant_id, data_domain, pose_event_id, review_seq),
	UNIQUE (tenant_id, data_domain, idempotency_key),
	CONSTRAINT ck_sequence CHECK (review_seq > 0),
	CONSTRAINT ck_status CHECK (status IN ('pending','confirmed','normal_movement','tracking_error','uncertain')),
	CONSTRAINT ck_note CHECK (length(note) <= 1000 AND length(reviewer_id) > 0)
)

;
