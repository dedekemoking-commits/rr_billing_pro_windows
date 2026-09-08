-- ============================================
-- CUSTOMER TRANSACTIONS TABLE (riwayat pembelian)
-- Jalankan di Supabase Dashboard > SQL Editor
-- Bisa dijalankan kapan saja (IF NOT EXISTS aman)
-- ============================================

CREATE TABLE IF NOT EXISTS "customer_transactions" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "owner" TEXT NOT NULL DEFAULT '',
    "customer_id" UUID NOT NULL,
    "jenis" TEXT NOT NULL DEFAULT 'topup',
    "deskripsi" TEXT NOT NULL DEFAULT '',
    "jumlah_menit" INTEGER NOT NULL DEFAULT 0,
    "nominal" INTEGER NOT NULL DEFAULT 0,
    "ref" TEXT NOT NULL DEFAULT '',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE ("owner", "ref")
);

CREATE INDEX IF NOT EXISTS idx_customer_transactions_owner ON "customer_transactions"("owner");
CREATE INDEX IF NOT EXISTS idx_customer_transactions_customer ON "customer_transactions"("customer_id");
CREATE INDEX IF NOT EXISTS idx_customer_transactions_created ON "customer_transactions"("created_at");

ALTER TABLE "customer_transactions" DISABLE ROW LEVEL SECURITY;

ALTER PUBLICATION supabase_realtime ADD TABLE "customer_transactions";