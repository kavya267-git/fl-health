-- Run this in your Supabase SQL Editor to update your tables

-- 1. Add missing columns to training_history
ALTER TABLE public.training_history 
  ADD COLUMN IF NOT EXISTS data_type text,
  ADD COLUMN IF NOT EXISTS file_name text,
  ADD COLUMN IF NOT EXISTS feature_count integer,
  ADD COLUMN IF NOT EXISTS privacy_score double precision,
  ADD COLUMN IF NOT EXISTS model_hash text,
  ADD COLUMN IF NOT EXISTS upload_id uuid;

-- 2. Create the uploads table if it doesn't exist
CREATE TABLE IF NOT EXISTS public.uploads (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  hospital_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
  file_name text,
  file_type text,
  file_size bigint,
  file_count integer,
  ehr_count integer,
  ecg_count integer,
  xray_count integer,
  other_count integer,
  storage_path text,
  upload_status text DEFAULT 'completed',
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now())
);

-- 3. Add missing columns to hospitals table
ALTER TABLE public.hospitals
  ADD COLUMN IF NOT EXISTS total_patients integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS feature_count integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS data_type text,
  ADD COLUMN IF NOT EXISTS data_file_path text,
  ADD COLUMN IF NOT EXISTS ecg_count integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS xray_count integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_upload_id uuid,
  ADD COLUMN IF NOT EXISTS last_upload_at timestamp with time zone,
  ADD COLUMN IF NOT EXISTS local_accuracy double precision,
  ADD COLUMN IF NOT EXISTS privacy_score double precision,
  ADD COLUMN IF NOT EXISTS last_trained_at timestamp with time zone,
  ADD COLUMN IF NOT EXISTS last_trained_file text;
