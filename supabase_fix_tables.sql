-- ============================================
-- FIX: Recreate tables dengan DOUBLE QUOTES
-- supaya camelCase column names terjaga.
-- Jalankan di Supabase Dashboard > SQL Editor
-- ============================================

-- 1. Drop old tables
DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS call_meta;
DROP TABLE IF EXISTS rental_status;

-- 2. bookings (dengan double quotes untuk camelCase)
CREATE TABLE "bookings" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "owner" TEXT NOT NULL DEFAULT '',
    "namaPelanggan" TEXT NOT NULL DEFAULT '',
    "noHp" TEXT NOT NULL DEFAULT '',
    "perangkat" TEXT NOT NULL DEFAULT '',
    "grup" TEXT NOT NULL DEFAULT '',
    "paket" TEXT NOT NULL DEFAULT '',
    "totalHarga" INTEGER NOT NULL DEFAULT 0,
    "tanggal" TEXT NOT NULL DEFAULT '',
    "jam" TEXT NOT NULL DEFAULT '',
    "metode" TEXT NOT NULL DEFAULT 'biasa',
    "statusBayar" TEXT NOT NULL DEFAULT 'belum_bayar',
    "nominalTransfer" INTEGER NOT NULL DEFAULT 0,
    "nominalDp" INTEGER NOT NULL DEFAULT 0,
    "sisaBayar" INTEGER NOT NULL DEFAULT 0,
    "pesanan" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "catatan" TEXT NOT NULL DEFAULT '',
    "status" TEXT NOT NULL DEFAULT 'baru',
    "kasir" TEXT NOT NULL DEFAULT '',
    "alasan" TEXT NOT NULL DEFAULT '',
    "bukti" TEXT NOT NULL DEFAULT '',
    "createdAt" TEXT NOT NULL DEFAULT '',
    "updatedAt" TEXT NOT NULL DEFAULT '',
    "sesiDimulai" BOOLEAN NOT NULL DEFAULT false,
    "sesiDimulaiAt" TEXT NOT NULL DEFAULT '',
    "sesiLabel" TEXT NOT NULL DEFAULT '',
    "pelunasanSisa" INTEGER NOT NULL DEFAULT 0,
    "lunasAt" TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_bookings_owner ON "bookings"("owner");
CREATE INDEX IF NOT EXISTS idx_bookings_status ON "bookings"("status");
CREATE INDEX IF NOT EXISTS idx_bookings_owner_status ON "bookings"("owner", "status");
CREATE INDEX IF NOT EXISTS idx_bookings_tanggal ON "bookings"("tanggal");
CREATE INDEX IF NOT EXISTS idx_bookings_createdAt ON "bookings"("createdAt" DESC);

ALTER PUBLICATION supabase_realtime ADD TABLE "bookings";

-- 3. call_meta (dengan double quotes untuk camelCase)
CREATE TABLE "call_meta" (
    "id" TEXT PRIMARY KEY,
    "owner" TEXT NOT NULL DEFAULT '',
    "nama_rental" TEXT NOT NULL DEFAULT '',
    "logo" TEXT NOT NULL DEFAULT '',
    "no_hp" TEXT NOT NULL DEFAULT '',
    "nama_dana" TEXT NOT NULL DEFAULT '',
    "no_dana" TEXT NOT NULL DEFAULT '',
    "alamat" TEXT NOT NULL DEFAULT '',
    "qr_pembayaran" TEXT NOT NULL DEFAULT '',
    "daftar_tv" JSONB NOT NULL DEFAULT '[]'::jsonb,
    "devices" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "tv_status" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "paket_grup" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "makanan" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "minuman" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "stok" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "stok_min" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "booking_ops" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "overlay_setting" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "updatedAt" TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_call_meta_owner ON "call_meta"("owner");

-- 4. rental_status
CREATE TABLE "rental_status" (
    "id" TEXT PRIMARY KEY,
    "owner" TEXT NOT NULL DEFAULT '',
    "status" TEXT NOT NULL DEFAULT 'buka',
    "jam_buka" TEXT NOT NULL DEFAULT '',
    "jam_tutup" TEXT NOT NULL DEFAULT '',
    "updatedAt" TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_rental_status_owner ON "rental_status"("owner");

-- 5. Disable RLS
ALTER TABLE "bookings" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "call_meta" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "rental_status" DISABLE ROW LEVEL SECURITY;
