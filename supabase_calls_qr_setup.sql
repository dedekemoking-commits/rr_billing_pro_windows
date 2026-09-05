-- ============================================
-- CALLS + QR_SESSIONS tables untuk Supabase
-- Jalankan di Supabase Dashboard > SQL Editor
-- ============================================

-- 1. calls (panggilan pelanggan ke kasir)
CREATE TABLE "calls" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "tv" TEXT NOT NULL DEFAULT '',
    "kode" TEXT NOT NULL DEFAULT '',
    "jenis" TEXT NOT NULL DEFAULT 'keluhan',
    "item" JSONB NOT NULL DEFAULT '[]'::jsonb,
    "items" JSONB NOT NULL DEFAULT '[]'::jsonb,
    "catatan" TEXT NOT NULL DEFAULT '',
    "ts" BIGINT NOT NULL DEFAULT 0,
    "sid" TEXT NOT NULL DEFAULT '',
    "createdAt" TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_calls_ts ON "calls"("ts" DESC);
CREATE INDEX IF NOT EXISTS idx_calls_kode ON "calls"("kode");

-- 2. qr_sessions (PIN verifikasi)
CREATE TABLE "qr_sessions" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "tv" TEXT NOT NULL DEFAULT '',
    "kode" TEXT NOT NULL DEFAULT '',
    "pin" TEXT NOT NULL DEFAULT '',
    "pin_user" TEXT NOT NULL DEFAULT '',
    "pin_set_at" BIGINT NOT NULL DEFAULT 0,
    "tries" INTEGER NOT NULL DEFAULT 0,
    "reason" TEXT NOT NULL DEFAULT '',
    "owner" TEXT NOT NULL DEFAULT '',
    "status" TEXT NOT NULL DEFAULT 'baru',
    "sid" TEXT NOT NULL DEFAULT '',
    "created" BIGINT NOT NULL DEFAULT 0,
    "updatedAt" TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_qr_sessions_created ON "qr_sessions"("created" DESC);
CREATE INDEX IF NOT EXISTS idx_qr_sessions_owner ON "qr_sessions"("owner");

-- 3. Disable RLS
ALTER TABLE "calls" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "qr_sessions" DISABLE ROW LEVEL SECURITY;

-- 4. Enable Realtime untuk calls (agar bisa dipantau)
ALTER PUBLICATION supabase_realtime ADD TABLE "calls";

-- 5. Tambah kolom yang belum ada (jika tabel sudah dibuat sebelumnya)
ALTER TABLE "qr_sessions" ADD COLUMN IF NOT EXISTS "pin_set_at" BIGINT NOT NULL DEFAULT 0;
ALTER TABLE "qr_sessions" ADD COLUMN IF NOT EXISTS "tries" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "qr_sessions" ADD COLUMN IF NOT EXISTS "reason" TEXT NOT NULL DEFAULT '';
