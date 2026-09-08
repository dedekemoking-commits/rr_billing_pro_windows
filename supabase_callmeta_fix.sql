-- Drop old call_meta and recreate with all needed columns
DROP TABLE IF EXISTS call_meta;

CREATE TABLE call_meta (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    nama_rental TEXT NOT NULL DEFAULT '',
    logo TEXT NOT NULL DEFAULT '',
    no_hp TEXT NOT NULL DEFAULT '',
    nama_dana TEXT NOT NULL DEFAULT '',
    no_dana TEXT NOT NULL DEFAULT '',
    alamat TEXT NOT NULL DEFAULT '',
    qr_pembayaran TEXT NOT NULL DEFAULT '',
    daftar_tv JSONB NOT NULL DEFAULT '[]'::jsonb,
    devices JSONB NOT NULL DEFAULT '{}'::jsonb,
    tv_status JSONB NOT NULL DEFAULT '{}'::jsonb,
    paket_grup JSONB NOT NULL DEFAULT '{}'::jsonb,
    makanan JSONB NOT NULL DEFAULT '{}'::jsonb,
    minuman JSONB NOT NULL DEFAULT '{}'::jsonb,
    stok JSONB NOT NULL DEFAULT '{}'::jsonb,
    stok_min JSONB NOT NULL DEFAULT '{}'::jsonb,
    booking_ops JSONB NOT NULL DEFAULT '{}'::jsonb,
    overlay_setting JSONB NOT NULL DEFAULT '{}'::jsonb,
    updatedAt TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_call_meta_owner ON call_meta(owner);
ALTER TABLE call_meta DISABLE ROW LEVEL SECURITY;
