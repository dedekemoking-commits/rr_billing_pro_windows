package com.rrbillingpro.tvclient.util

import android.content.Context
import android.content.SharedPreferences

object Prefs {
    private const val FILE = "rr_tv_client"
    private const val KEY_HOST = "server_host"
    private const val KEY_PORT = "server_port"
    private const val KEY_MEJA = "meja_id"
    private const val KEY_AUTO_START = "auto_start"
    private const val KEY_PROMO_URL = "promo_url"
    private const val KEY_PROMO_TYPE = "promo_type"
    private const val KEY_LOCKED = "locked"
    private const val KEY_LOCK_MEJA = "lock_meja"
    private const val KEY_LOCK_SEWA = "lock_sewa"
    private const val KEY_LOCK_FNB = "lock_fnb"
    private const val KEY_LOCK_TOTAL = "lock_total"
    private const val KEY_LOCK_SEWA_HARGA = "lock_sewa_harga"
    private const val KEY_LOCK_SEWA_LUNAS = "lock_sewa_lunas"
    private const val KEY_LOCK_LUNAS_TOTAL = "lock_lunas_total"
    private const val KEY_LOCK_TAGIHAN_TOTAL = "lock_tagihan_total"
    private const val KEY_LOCK_LOGO = "lock_logo"
    private const val KEY_LOCK_PROMO = "lock_promo"
    private const val KEY_LOCK_PESAN = "lock_pesan"
    private const val KEY_LOCK_NOTICE = "lock_notice"
    private const val KEY_LOCK_LAST_TIME_IMAGE = "lock_last_time_image"
    private const val KEY_LOCK_BG = "lock_bg_video"
    private const val KEY_LAST_INPUT = "last_used_input"
    private const val KEY_HDMI_PORT = "hdmi_port"
    private const val KEY_HDMI_HINT = "hdmi_input_hint"
    private const val KEY_SESI = "sesi_snapshot"
    private const val KEY_LEGACY_UNINSTALL_PROMPTED = "legacy_uninstall_prompted"


    private fun sp(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun host(ctx: Context): String = sp(ctx).getString(KEY_HOST, "192.168.1.100") ?: "192.168.1.100"

    fun port(ctx: Context): Int = sp(ctx).getInt(KEY_PORT, 8080)

    fun mejaId(ctx: Context): String = sp(ctx).getString(KEY_MEJA, "TV 1") ?: "TV 1"

    fun autoStart(ctx: Context): Boolean = sp(ctx).getBoolean(KEY_AUTO_START, false)

    fun legacyUninstallPrompted(ctx: Context): Boolean =
        sp(ctx).getBoolean(KEY_LEGACY_UNINSTALL_PROMPTED, false)

    fun setLegacyUninstallPrompted(ctx: Context) {
        sp(ctx).edit().putBoolean(KEY_LEGACY_UNINSTALL_PROMPTED, true).apply()
    }

    fun promoUrl(ctx: Context): String = sp(ctx).getString(KEY_PROMO_URL, "") ?: ""

    fun promoType(ctx: Context): String = sp(ctx).getString(KEY_PROMO_TYPE, "video") ?: "video"

    fun savePromo(ctx: Context, url: String, type: String) {
        sp(ctx).edit()
            .putString(KEY_PROMO_URL, url.trim())
            .putString(KEY_PROMO_TYPE, if (type.isBlank()) "video" else type)
            .apply()
    }

    fun save(ctx: Context, host: String, port: Int, mejaId: String, autoStart: Boolean) {
        sp(ctx).edit()
            .putString(KEY_HOST, host.trim())
            .putInt(KEY_PORT, port)
            .putString(KEY_MEJA, mejaId.trim())
            .putBoolean(KEY_AUTO_START, autoStart)
            .apply()
    }

    // ── Firestore sync identity ──────────────────────────────────────────────
    private const val KEY_TV_ID = "tv_id"
    private const val KEY_USERNAME = "username"

    fun tvId(ctx: Context): String = sp(ctx).getString(KEY_TV_ID, "tv-main") ?: "tv-main"

    fun username(ctx: Context): String = sp(ctx).getString(KEY_USERNAME, "") ?: ""

    fun isLocked(ctx: Context): Boolean = sp(ctx).getBoolean(KEY_LOCKED, false)

    fun saveLock(ctx: Context, d: com.rrbillingpro.tvclient.model.LockDetail?) {
        val ed = sp(ctx).edit()
        ed.putBoolean(KEY_LOCKED, d != null)
        if (d != null) {
            ed.putString(KEY_LOCK_MEJA, d.meja)
            ed.putString(KEY_LOCK_SEWA, d.sewa)
            ed.putString(KEY_LOCK_FNB, d.fnb)
            ed.putString(KEY_LOCK_TOTAL, d.total)
            ed.putString(KEY_LOCK_SEWA_HARGA, d.sewaHarga)
            ed.putBoolean(KEY_LOCK_SEWA_LUNAS, d.sewaLunas)
            ed.putString(KEY_LOCK_LUNAS_TOTAL, d.lunasTotal)
            ed.putString(KEY_LOCK_TAGIHAN_TOTAL, d.tagihanTotal)
            ed.putString(KEY_LOCK_LOGO, d.logoUrl)
            ed.putString(KEY_LOCK_PROMO, d.promoUrl)
            ed.putString(KEY_LOCK_PESAN, d.pesan)
            ed.putString(KEY_LOCK_NOTICE, d.notice)
            ed.putString(KEY_LOCK_LAST_TIME_IMAGE, d.lastTimeImageUrl)
        }
        ed.apply()
    }

    fun clearLock(ctx: Context) {
        sp(ctx).edit().putBoolean(KEY_LOCKED, false).apply()
    }

    fun lockDetail(ctx: Context): com.rrbillingpro.tvclient.model.LockDetail {
        val s = sp(ctx)
        return com.rrbillingpro.tvclient.model.LockDetail(
            meja = s.getString(KEY_LOCK_MEJA, "MEJA") ?: "MEJA",
            sewa = s.getString(KEY_LOCK_SEWA, "-") ?: "-",
            fnb = s.getString(KEY_LOCK_FNB, "Rp 0") ?: "Rp 0",
            total = s.getString(KEY_LOCK_TOTAL, "Rp 0") ?: "Rp 0",
            sewaHarga = s.getString(KEY_LOCK_SEWA_HARGA, "") ?: "",
            sewaLunas = s.getBoolean(KEY_LOCK_SEWA_LUNAS, true),
            lunasTotal = s.getString(KEY_LOCK_LUNAS_TOTAL, "") ?: "",
            tagihanTotal = s.getString(KEY_LOCK_TAGIHAN_TOTAL, "") ?: "",
            logoUrl = s.getString(KEY_LOCK_LOGO, "") ?: "",
            promoUrl = s.getString(KEY_LOCK_PROMO, "") ?: "",
            pesan = s.getString(KEY_LOCK_PESAN, "WAKTU SEWA HABIS")
                ?: "WAKTU SEWA HABIS",
            notice = s.getString(KEY_LOCK_NOTICE, "") ?: "",
            lastTimeImageUrl = s.getString(KEY_LOCK_LAST_TIME_IMAGE, "") ?: "",
        )
    }

    fun getLastInput(ctx: Context): String = sp(ctx).getString(KEY_LAST_INPUT, "") ?: ""

    /**
     * URL MP4 loop untuk background lockscreen. Diisi kasir lewat
     * Overlay → Upload Gambar Bergerak, lalu dikirim server sebagai
     * UPDATE_LOCK_BG. Kosong = pakai gambar bawaan aplikasi.
     */
    fun lockBgUrl(ctx: Context): String = sp(ctx).getString(KEY_LOCK_BG, "") ?: ""

    fun saveLockBg(ctx: Context, url: String) {
        sp(ctx).edit().putString(KEY_LOCK_BG, url.trim()).apply()
    }
    fun saveLastInput(ctx: Context, inputId: String) {
        sp(ctx).edit().putString(KEY_LAST_INPUT, inputId).apply()
    }

    // ── Port HDMI pilihan kasir (dikirim via START_TIMER/SYNC_TIMER) ─────────
    //  Nila:
    //   1..4  = pindah otomatis ke port itu setelah promo selesai
    //   0     = kasir belum mengisi — JANGAN sentuh input (perilaku lama aman)
    //   -1    = "Jangan pakai" — TV yang mengatur inputnya sendiri (native)
    // Default 0: tanpa info dari kasir, app tidak pernah menebak port.

    fun hdmiPort(ctx: Context): Int = sp(ctx).getInt(KEY_HDMI_PORT, 0)

    fun hdmiInputHint(ctx: Context): String =
        sp(ctx).getString(KEY_HDMI_HINT, "") ?: ""

    fun saveHdmi(ctx: Context, port: Int, hint: String?) {
        val ed = sp(ctx).edit().putInt(KEY_HDMI_PORT, port)
        if (hint != null) ed.putString(KEY_HDMI_HINT, hint.trim())
        ed.apply()
    }

    // ── Aset media lokal (dikirim kasir lewat adb push) ──────────────────────
    // PENTING: semua berbagi folder yang sama dengan target adb push:
    // /sdcard/Android/data/com.rrbillingpro.tvclient/files/media/
    // Nama tetap: promo.mp4, lockscreen.mp4, promo.jpg, logo.png — saat kasir
    // ganti video, file lama ditimpa (overwrite) dengan nama yang sama.

    fun mediaDir(ctx: Context): java.io.File {
        val base = ctx.getExternalFilesDir(null) ?: ctx.filesDir
        val d = java.io.File(base, "media")
        if (!d.exists()) d.mkdirs()
        return d
    }

    fun mediaFile(ctx: Context, name: String): java.io.File =
        java.io.File(mediaDir(ctx), name)

    fun adaMediaLokal(ctx: Context, name: String): Boolean {
        val f = mediaFile(ctx, name)
        return f.exists() && f.length() > 0
    }

    fun saveAutoStart(ctx: Context, enabled: Boolean) {

        sp(ctx).edit().putBoolean(KEY_AUTO_START, enabled).apply()
    }

    // ── Snapshot sesi (persistensi offline) ──────────────────────────────────
    // Kasir mengirim START/PAUSE/SYNC tiap detik; snapshot ini disimpan di TV
    // supaya saat CLI putus / TV mati-nyala, popup waktu & sisa sewa tetap
    // hidup dan countdown lanjut lokal. Isi = JSON (lihat TvOverlayService).

    fun sesiSnapshot(ctx: Context): String =
        sp(ctx).getString(KEY_SESI, "") ?: ""

    fun saveSesiSnapshot(ctx: Context, json: String) {
        sp(ctx).edit().putString(KEY_SESI, json).apply()
    }

    fun clearSesiSnapshot(ctx: Context) {
        sp(ctx).edit().remove(KEY_SESI).apply()
    }

    // ── Gaya popup timer/PIN (dikirim kasir lewat OVERLAY_STYLE) ─────────────
    // Disimpan di TV supaya gaya tetap sama setelah app di-restart / TV
    // dimatikan, dan dipakai sebagai nilai awal saat overlay pertama kali
    // inflated (nilai bawaan perangkat keras tetap berlaku bila kasir
    // belum pernah mengirim apa pun).

    private const val KEY_OVERLAY_MODE = "overlay_mode"
    private const val KEY_OVERLAY_LAST_MINUTES = "overlay_last_minutes"
    private const val KEY_BEBAS_START_DURASI = "bebas_start_durasi"
    private const val KEY_BEBAS_INTERVAL = "bebas_interval"
    private const val KEY_BEBAS_DURASI = "bebas_durasi"

    fun saveOverlayConfig(ctx: Context, mode: String, lastMinutes: Int,
                          startDurasi: Int, interval: Int, durasi: Int) {
        sp(ctx).edit()
            .putString(KEY_OVERLAY_MODE, mode)
            .putInt(KEY_OVERLAY_LAST_MINUTES, lastMinutes.coerceIn(1, 120))
            .putInt(KEY_BEBAS_START_DURASI, startDurasi.coerceIn(0, 120))
            .putInt(KEY_BEBAS_INTERVAL, interval.coerceIn(1, 1440))
            .putInt(KEY_BEBAS_DURASI, durasi.coerceIn(1, 120))
            .apply()
    }

    fun overlayMode(ctx: Context): String = sp(ctx).getString(KEY_OVERLAY_MODE, "always") ?: "always"
    fun overlayLastMinutes(ctx: Context): Int = sp(ctx).getInt(KEY_OVERLAY_LAST_MINUTES, 3)
    fun bebasStartDurasi(ctx: Context): Int = sp(ctx).getInt(KEY_BEBAS_START_DURASI, 5)
    fun bebasInterval(ctx: Context): Int = sp(ctx).getInt(KEY_BEBAS_INTERVAL, 60)
    fun bebasDurasi(ctx: Context): Int = sp(ctx).getInt(KEY_BEBAS_DURASI, 10)

    private const val KEY_ALPHA = "overlay_bg_alpha"
    private const val KEY_ACCENT = "overlay_accent"
    private const val KEY_RADIUS = "overlay_radius"
    private const val KEY_TIMER_SIZE = "overlay_timer_size"
    private const val KEY_SCALE = "overlay_scale"
    private const val KEY_POS_Y = "overlay_pos_y"

    fun saveOverlayStyle(ctx: Context, alpha: Int, accent: String,
                         radius: Int, timerSize: Int, scale: Int, posY: Int) {
        sp(ctx).edit()
            .putInt(KEY_ALPHA, alpha.coerceIn(0, 100))
            .putString(KEY_ACCENT, accent)
            .putInt(KEY_RADIUS, radius.coerceIn(0, 40))
            .putInt(KEY_TIMER_SIZE, timerSize.coerceIn(12, 48))
            .putInt(KEY_SCALE, scale.coerceIn(50, 130))
            .putInt(KEY_POS_Y, posY.coerceIn(0, 60))
            .apply()
    }

    fun overlayStyle(ctx: Context): OverlayStyle {
        val s = sp(ctx)
        val hex = (s.getString(KEY_ACCENT, "") ?: "").trim().trimStart('#')
        val accent = if (hex.length == 6) "#$hex".uppercase() else DEFAULT_ACCENT
        return OverlayStyle(
            alpha = s.getInt(KEY_ALPHA, DEFAULT_ALPHA),
            accent = accent,
            radius = s.getInt(KEY_RADIUS, DEFAULT_RADIUS),
            timerSize = s.getInt(KEY_TIMER_SIZE, DEFAULT_TIMER_SIZE),
            scale = s.getInt(KEY_SCALE, DEFAULT_SCALE),
            posY = s.getInt(KEY_POS_Y, DEFAULT_POS_Y),
        )
    }

    /** Gaya popup; `s` = faktor skala dalam persen (70 = 70%). */
    data class OverlayStyle(
        val alpha: Int,
        val accent: String,
        val radius: Int,
        val timerSize: Int,
        val scale: Int,
        val posY: Int,
    ) {
        fun s(): Float = scale.coerceIn(50, 130) / 100f
    }

    const val DEFAULT_ALPHA = 80
    const val DEFAULT_ACCENT = "#00E5FF"
    const val DEFAULT_RADIUS = 14
    const val DEFAULT_TIMER_SIZE = 22
    const val DEFAULT_SCALE = 70
    const val DEFAULT_POS_Y = 20
}
