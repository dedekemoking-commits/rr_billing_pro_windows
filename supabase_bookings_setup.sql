-- ============================================
-- BOOKING TABLE FOR RRBILLINGPRO
-- Jalankan di Supabase Dashboard > SQL Editor
-- ============================================

-- 1. Buat tabel bookings
CREATE TABLE IF NOT EXISTS bookings (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    namaPelanggan TEXT NOT NULL DEFAULT '',
    noHp TEXT NOT NULL DEFAULT '',
    perangkat TEXT NOT NULL DEFAULT '',
    grup TEXT NOT NULL DEFAULT '',
    paket TEXT NOT NULL DEFAULT '',
    totalHarga INTEGER NOT NULL DEFAULT 0,
    tanggal TEXT NOT NULL DEFAULT '',
    jam TEXT NOT NULL DEFAULT '',
    metode TEXT NOT NULL DEFAULT 'biasa',
    statusBayar TEXT NOT NULL DEFAULT 'belum_bayar',
    nominalTransfer INTEGER NOT NULL DEFAULT 0,
    nominalDp INTEGER NOT NULL DEFAULT 0,
    sisaBayar INTEGER NOT NULL DEFAULT 0,
    pesanan JSONB NOT NULL DEFAULT '{}'::jsonb,
    catatan TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'baru',
    kasir TEXT NOT NULL DEFAULT '',
    alasan TEXT NOT NULL DEFAULT '',
    bukti TEXT NOT NULL DEFAULT '',
    createdAt TEXT NOT NULL DEFAULT '',
    updatedAt TEXT NOT NULL DEFAULT '',
    sesiDimulai BOOLEAN NOT NULL DEFAULT false,
    sesiDimulaiAt TEXT NOT NULL DEFAULT '',
    sesiLabel TEXT NOT NULL DEFAULT '',
    pelunasanSisa INTEGER NOT NULL DEFAULT 0,
    lunasAt TEXT NOT NULL DEFAULT ''
);

-- 2. Index untuk query cepat
CREATE INDEX IF NOT EXISTS idx_bookings_owner ON bookings(owner);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_bookings_owner_status ON bookings(owner, status);
CREATE INDEX IF NOT EXISTS idx_bookings_tanggal ON bookings(tanggal);
CREATE INDEX IF NOT EXISTS idx_bookings_createdAt ON bookings(createdAt DESC);

-- 3. Enable Realtime (agar booking.html bisa listen perubahan status)
ALTER PUBLICATION supabase_realtime ADD TABLE bookings;

-- 4. Buat tabel call_meta (untuk device status, no_hp, tarif grup)
CREATE TABLE IF NOT EXISTS call_meta (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    devices JSONB NOT NULL DEFAULT '[]'::jsonb,
    tv_status JSONB NOT NULL DEFAULT '{}'::jsonb,
    no_hp TEXT NOT NULL DEFAULT '',
    updatedAt TEXT NOT NULL DEFAULT ''
);

-- 5. Buat tabel rental_status (operational status: buka/tutup/libur)
CREATE TABLE IF NOT EXISTS rental_status (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'buka',
    jam_buka TEXT NOT NULL DEFAULT '',
    jam_tutup TEXT NOT NULL DEFAULT '',
    updatedAt TEXT NOT NULL DEFAULT ''
);

-- 6. Index untuk call_meta dan rental_status
CREATE INDEX IF NOT EXISTS idx_call_meta_owner ON call_meta(owner);
CREATE INDEX IF NOT EXISTS idx_rental_status_owner ON rental_status(owner);

-- 7. Disable RLS (karena desktop app pakai service_role, website pakai anon)
ALTER TABLE bookings DISABLE ROW LEVEL SECURITY;
ALTER TABLE call_meta DISABLE ROW LEVEL SECURITY;
ALTER TABLE rental_status DISABLE ROW LEVEL SECURITY;
