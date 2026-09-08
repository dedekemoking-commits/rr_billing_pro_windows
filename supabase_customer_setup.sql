-- ============================================
-- CUSTOMER APP TABLES untuk Supabase
-- Jalankan di Supabase Dashboard > SQL Editor
-- ============================================

-- 1. customers (pelanggan terdaftar)
CREATE TABLE IF NOT EXISTS "customers" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "firebase_uid" TEXT NOT NULL DEFAULT '',
    "owner" TEXT NOT NULL DEFAULT '',
    "nama" TEXT NOT NULL DEFAULT '',
    "email" TEXT NOT NULL DEFAULT '',
    "avatar_url" TEXT NOT NULL DEFAULT '',
    "saldo_waktu" INTEGER NOT NULL DEFAULT 0,
    "fcm_token" TEXT NOT NULL DEFAULT '',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE ("firebase_uid", "owner")
);

CREATE INDEX IF NOT EXISTS idx_customers_firebase_uid ON "customers"("firebase_uid");
CREATE INDEX IF NOT EXISTS idx_customers_owner ON "customers"("owner");
CREATE INDEX IF NOT EXISTS idx_customers_owner_uid ON "customers"("owner", "firebase_uid");

-- 2. vouchers (kode promo)
CREATE TABLE IF NOT EXISTS "vouchers" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "owner" TEXT NOT NULL DEFAULT '',
    "kode" TEXT NOT NULL DEFAULT '',
    "jenis" TEXT NOT NULL DEFAULT 'persen',
    "nilai" INTEGER NOT NULL DEFAULT 0,
    "min_transaksi" INTEGER NOT NULL DEFAULT 0,
    "max_penggunaan" INTEGER,
    "penggunaan" INTEGER NOT NULL DEFAULT 0,
    "berlaku_dari" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "berlaku_sampai" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "aktif" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE ("owner", "kode")
);

CREATE INDEX IF NOT EXISTS idx_vouchers_owner ON "vouchers"("owner");
CREATE INDEX IF NOT EXISTS idx_vouchers_owner_kode ON "vouchers"("owner", "kode");

-- 3. promo (promo aktif)
CREATE TABLE IF NOT EXISTS "promo" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "owner" TEXT NOT NULL DEFAULT '',
    "judul" TEXT NOT NULL DEFAULT '',
    "deskripsi" TEXT NOT NULL DEFAULT '',
    "gambar_url" TEXT NOT NULL DEFAULT '',
    "jenis" TEXT NOT NULL DEFAULT 'diskon_paket',
    "nilai" INTEGER NOT NULL DEFAULT 0,
    "berlaku_dari" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "berlaku_sampai" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "aktif" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_promo_owner ON "promo"("owner");

-- 4. customer_orders (pesanan F&B dari app pelanggan)
CREATE TABLE IF NOT EXISTS "customer_orders" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "owner" TEXT NOT NULL DEFAULT '',
    "customer_id" UUID NOT NULL,
    "items" JSONB NOT NULL DEFAULT '[]'::jsonb,
    "total" INTEGER NOT NULL DEFAULT 0,
    "status" TEXT NOT NULL DEFAULT 'baru',
    "catatan" TEXT NOT NULL DEFAULT '',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_customer_orders_owner ON "customer_orders"("owner");
CREATE INDEX IF NOT EXISTS idx_customer_orders_customer ON "customer_orders"("customer_id");

-- 5. Disable RLS
ALTER TABLE "customers" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "vouchers" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "promo" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "customer_orders" DISABLE ROW LEVEL SECURITY;

-- 6. Enable Realtime
ALTER PUBLICATION supabase_realtime ADD TABLE "customers";
ALTER PUBLICATION supabase_realtime ADD TABLE "vouchers";
ALTER PUBLICATION supabase_realtime ADD TABLE "promo";
ALTER PUBLICATION supabase_realtime ADD TABLE "customer_orders";
