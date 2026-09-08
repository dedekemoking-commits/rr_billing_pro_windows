-- ============================================
-- MEMBER SYSTEM TABLE for Supabase
-- Daftar member dari aplikasi pelanggan.
-- Jalankan di Supabase Dashboard > SQL Editor
-- ============================================

-- 1. members (kartu member pelanggan; 1 akun = banyak kartu per jenis)
CREATE TABLE IF NOT EXISTS "members" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "owner" TEXT NOT NULL DEFAULT '',
    "email" TEXT NOT NULL DEFAULT '',
    "nama" TEXT NOT NULL DEFAULT '',
    "no_hp" TEXT NOT NULL DEFAULT '',
    "jenis" TEXT NOT NULL DEFAULT '',
    "pin" TEXT NOT NULL DEFAULT '',
    "saldo_menit" INTEGER NOT NULL DEFAULT 0,
    "status" TEXT NOT NULL DEFAULT 'aktif',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE ("owner", "email", "jenis")
);

CREATE INDEX IF NOT EXISTS idx_members_owner ON "members"("owner");
CREATE INDEX IF NOT EXISTS idx_members_email ON "members"("email");
CREATE INDEX IF NOT EXISTS idx_members_owner_email ON "members"("owner", "email");
CREATE INDEX IF NOT EXISTS idx_members_owner_email_jenis ON "members"("owner", "email", "jenis");

-- 2. member_topup (permintaan isi waktu member dari app, menunggu konfirmasi kasir)
CREATE TABLE IF NOT EXISTS "member_topup" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "owner" TEXT NOT NULL DEFAULT '',
    "member_id" UUID NOT NULL,
    "email" TEXT NOT NULL DEFAULT '',
    "jenis" TEXT NOT NULL DEFAULT '',
    "paket_nama" TEXT NOT NULL DEFAULT '',
    "menit" INTEGER NOT NULL DEFAULT 0,
    "harga" INTEGER NOT NULL DEFAULT 0,
    "metode" TEXT NOT NULL DEFAULT '',
    "bukti" TEXT NOT NULL DEFAULT '',
    "status" TEXT NOT NULL DEFAULT 'menunggu',
    "kasir" TEXT NOT NULL DEFAULT '',
    "alasan" TEXT NOT NULL DEFAULT '',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE ("owner", "member_id", "created_at")
);

CREATE INDEX IF NOT EXISTS idx_member_topup_owner ON "member_topup"("owner");
CREATE INDEX IF NOT EXISTS idx_member_topup_member ON "member_topup"("member_id");
CREATE INDEX IF NOT EXISTS idx_member_topup_status ON "member_topup"("status");
CREATE INDEX IF NOT EXISTS idx_member_topup_email ON "member_topup"("email");

-- 3. Disable RLS (melalui backend service, abaikan untuk orisinal pending)
ALTER TABLE "members" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "member_topup" DISABLE ROW LEVEL SECURITY;

-- 4. Enable Realtime (kasir dapat notif permintaan isi member)
ALTER PUBLICATION supabase_realtime ADD TABLE "members";
ALTER PUBLICATION supabase_realtime ADD TABLE "member_topup";