-- Supabase Storage Setup for FL-Health
-- Run this in your Supabase SQL Editor to create the bucket for dataset and model storage.

-- 1. Create a bucket named "fl-health-data"
INSERT INTO storage.buckets (id, name, public) 
VALUES ('fl-health-data', 'fl-health-data', false)
ON CONFLICT (id) DO NOTHING;

-- 2. Allow Service Role to do everything (Backend uses service role key)
DROP POLICY IF EXISTS "Service role full access to storage" ON storage.objects;
CREATE POLICY "Service role full access to storage"
ON storage.objects FOR ALL
TO service_role
USING (bucket_id = 'fl-health-data')
WITH CHECK (bucket_id = 'fl-health-data');
