-- ============================================
-- SCHEMA LISENSI UNTUK RRBILLINGPRO (Supabase)
-- Jalankan di Supabase Dashboard > SQL Editor
-- ============================================

-- 1. invoices: permintaan lisensi dari aplikasi desktop / kasir
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    paket TEXT NOT NULL DEFAULT '',
    harga BIGINT NOT NULL DEFAULT 0,
    jumlah_tv INTEGER NOT NULL DEFAULT 0,
    "maxTv" INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'WAITING_CONFIRMATION',
    dibuat BIGINT NOT NULL DEFAULT 0,
    dibayar BIGINT NOT NULL DEFAULT 0,
    "confirmedBy" TEXT NOT NULL DEFAULT '',
    "kodeLisensi" TEXT NOT NULL DEFAULT '',
    "buktiBase64" TEXT NOT NULL DEFAULT '',
    bukti_local TEXT NOT NULL DEFAULT '',
    revoked BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_invoices_username ON invoices(username);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);

-- 2. notifications: request lisensi + notif ke app RR LICENSE GENERATOR
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    type TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    "user" TEXT NOT NULL DEFAULT '',
    paket TEXT NOT NULL DEFAULT '',
    harga BIGINT NOT NULL DEFAULT 0,
    jumlah_tv INTEGER NOT NULL DEFAULT 0,
    "invoiceId" TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    "sentAt" BIGINT NOT NULL DEFAULT 0,
    read BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);

-- 3. licenses: kode lisensi yang sudah di-generate admin
CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY,
    kode TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '',
    signature TEXT NOT NULL DEFAULT '',
    paket TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    expiry TEXT NOT NULL DEFAULT '',
    "generatedBy" TEXT NOT NULL DEFAULT '',
    "generatedAt" BIGINT NOT NULL DEFAULT 0,
    "activatedAt" BIGINT NOT NULL DEFAULT 0,
    "activatedDeviceId" TEXT NOT NULL DEFAULT '',
    revoked BOOLEAN NOT NULL DEFAULT false,
    "revokedAt" BIGINT NOT NULL DEFAULT 0,
    "revokedBy" TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_licenses_username ON licenses(username);
CREATE INDEX IF NOT EXISTS idx_licenses_generatedBy ON licenses("generatedBy");

-- 4. promo: pengaturan promo (global = 1 baris)
CREATE TABLE IF NOT EXISTS promo (
    id TEXT PRIMARY KEY,
    "promoAktif" BOOLEAN NOT NULL DEFAULT false,
    "diskonPerPaket" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "addTvOverride" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "updatedBy" TEXT NOT NULL DEFAULT '',
    "updatedAt" BIGINT NOT NULL DEFAULT 0,
    "newUserPromoActive" BOOLEAN NOT NULL DEFAULT false,
    "newUserDiscountPercent" INTEGER NOT NULL DEFAULT 30,
    "newUserPromoDurationHours" INTEGER NOT NULL DEFAULT 96,
    "newUserDiskonPerPaket" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "promoStartedAt" BIGINT NOT NULL DEFAULT 0,
    "promoDurationHours" INTEGER NOT NULL DEFAULT 0
);

-- 5. license_status: status lisensi tiap user (desktop restored dari sini)
CREATE TABLE IF NOT EXISTS license_status (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT '',
    pesan TEXT NOT NULL DEFAULT '',
    "expiresAt" TEXT NOT NULL DEFAULT '',
    "maxTv" BIGINT NOT NULL DEFAULT 0,
    "maxPc" BIGINT NOT NULL DEFAULT 0,
    "promoAddTv" BIGINT NOT NULL DEFAULT 0,
    "updatedAt" TEXT NOT NULL DEFAULT '',
    cloud_restored BOOLEAN NOT NULL DEFAULT false
);

-- 6. Disable RLS (akses via anon key)
ALTER TABLE invoices DISABLE ROW LEVEL SECURITY;
ALTER TABLE notifications DISABLE ROW LEVEL SECURITY;
ALTER TABLE licenses DISABLE ROW LEVEL SECURITY;
ALTER TABLE promo DISABLE ROW LEVEL SECURITY;
ALTER TABLE license_status DISABLE ROW LEVEL SECURITY;
