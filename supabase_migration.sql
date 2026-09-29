-- ═══════════════════════════════════════════════════════════════════════════
-- FL-Health Supabase Migration
-- Run this in: Supabase Dashboard → SQL Editor → New Query → Run
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── 1. uploads table ────────────────────────────────────────────────────────
-- Tracks every dataset upload per hospital.
CREATE TABLE IF NOT EXISTS uploads (
    id              UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    hospital_id     UUID         REFERENCES hospitals(id) ON DELETE CASCADE,
    file_name       TEXT         NOT NULL,
    file_type       TEXT         DEFAULT 'unknown',   -- 'ehr', 'ecg', 'image', 'zip'
    file_size       BIGINT       DEFAULT 0,           -- raw bytes of the uploaded file
    file_count      INT          DEFAULT 0,           -- total files after extraction
    ehr_count       INT          DEFAULT 0,
    ecg_count       INT          DEFAULT 0,
    xray_count      INT          DEFAULT 0,
    other_count     INT          DEFAULT 0,
    storage_path    TEXT         DEFAULT '',          -- Supabase Storage path (persists across restarts)
    upload_status   TEXT         DEFAULT 'completed', -- 'completed' | 'cleared'
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

-- Safe ALTER in case the table already exists without storage_path
ALTER TABLE uploads
    ADD COLUMN IF NOT EXISTS storage_path TEXT DEFAULT '';

-- Index for fast per-hospital lookups
CREATE INDEX IF NOT EXISTS idx_uploads_hospital_id ON uploads(hospital_id);
CREATE INDEX IF NOT EXISTS idx_uploads_created_at  ON uploads(created_at DESC);

-- ─── 2. model_versions table ──────────────────────────────────────────────────
-- Stores a record every time a federated aggregation is triggered.
CREATE TABLE IF NOT EXISTS model_versions (
    id                     BIGSERIAL    PRIMARY KEY,
    round_number           INT          NOT NULL,
    hospitals_contributed  INT          DEFAULT 0,
    byzantine_excluded     INT          DEFAULT 0,   -- hospitals flagged as Byzantine
    dropout_rate           FLOAT        DEFAULT 0.0, -- fraction of clients that dropped
    model_hash             TEXT         DEFAULT '',
    storage_path           TEXT         DEFAULT '',  -- path in Supabase Storage
    created_at             TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_versions_round ON model_versions(round_number);

-- Safe ALTER in case the table already exists without the new columns
ALTER TABLE model_versions
    ADD COLUMN IF NOT EXISTS byzantine_excluded INT     DEFAULT 0,
    ADD COLUMN IF NOT EXISTS dropout_rate       FLOAT   DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS storage_path       TEXT    DEFAULT '';

-- ─── 3. fl_round_state table ─────────────────────────────────────────────────
-- Single-row table that persists the current FL round number across server restarts.
CREATE TABLE IF NOT EXISTS fl_round_state (
    id             INT          PRIMARY KEY DEFAULT 1,
    round_number   INT          NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ  DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);

-- Insert the initial row (harmless if already present)
INSERT INTO fl_round_state (id, round_number)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

-- ─── 4. Extend training_history with new columns ──────────────────────────────
-- Add columns if they don't already exist (safe to run multiple times).
ALTER TABLE training_history
    ADD COLUMN IF NOT EXISTS data_type      TEXT,
    ADD COLUMN IF NOT EXISTS file_name      TEXT,
    ADD COLUMN IF NOT EXISTS feature_count  INT,
    ADD COLUMN IF NOT EXISTS privacy_score  FLOAT,
    ADD COLUMN IF NOT EXISTS model_hash     TEXT,
    ADD COLUMN IF NOT EXISTS upload_id      UUID REFERENCES uploads(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_at     TIMESTAMPTZ DEFAULT NOW();

-- ─── 5. Extend hospitals with new tracking columns ───────────────────────────
ALTER TABLE hospitals
    ADD COLUMN IF NOT EXISTS ecg_count        INT          DEFAULT 0,
    ADD COLUMN IF NOT EXISTS xray_count       INT          DEFAULT 0,
    ADD COLUMN IF NOT EXISTS feature_count    INT          DEFAULT 0,
    ADD COLUMN IF NOT EXISTS data_file_path   TEXT,
    ADD COLUMN IF NOT EXISTS last_upload_id   UUID REFERENCES uploads(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS last_upload_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_trained_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_trained_file TEXT;

-- ─── 6. Row Level Security (RLS) — uploads ───────────────────────────────────
-- Enable RLS so hospitals can only see their own uploads.
ALTER TABLE uploads ENABLE ROW LEVEL SECURITY;

-- Allow hospitals to see only their own uploads
DROP POLICY IF EXISTS "Hospital sees own uploads" ON uploads;
CREATE POLICY "Hospital sees own uploads"
    ON uploads FOR SELECT
    USING (auth.uid() = hospital_id);

-- Allow service role (backend) to read/write everything
DROP POLICY IF EXISTS "Service role full access uploads" ON uploads;
CREATE POLICY "Service role full access uploads"
    ON uploads FOR ALL
    USING (auth.role() = 'service_role');

-- ─── 7. RLS for model_versions (admin-only via service role) ─────────────────
ALTER TABLE model_versions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access model_versions" ON model_versions;
CREATE POLICY "Service role full access model_versions"
    ON model_versions FOR ALL
    USING (auth.role() = 'service_role');

-- ─── 8. RLS for fl_round_state ───────────────────────────────────────────────
ALTER TABLE fl_round_state ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access fl_round_state" ON fl_round_state;
CREATE POLICY "Service role full access fl_round_state"
    ON fl_round_state FOR ALL
    USING (auth.role() = 'service_role');

-- ─── Done ─────────────────────────────────────────────────────────────────────
-- After running this, verify with:
--   SELECT table_name FROM information_schema.tables
--   WHERE table_schema = 'public' ORDER BY table_name;
