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
    private const val KEY_LOCK_BG = "lock_bg_video"
    private const val KEY_LAST_INPUT = "last_used_input"


    private fun sp(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun host(ctx: Context): String = sp(ctx).getString(KEY_HOST, "192.168.1.100") ?: "192.168.1.100"

    fun port(ctx: Context): Int = sp(ctx).getInt(KEY_PORT, 8080)

    fun mejaId(ctx: Context): String = sp(ctx).getString(KEY_MEJA, "TV 1") ?: "TV 1"

    fun autoStart(ctx: Context): Boolean = sp(ctx).getBoolean(KEY_AUTO_START, false)

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

    fun saveAutoStart(ctx: Context, enabled: Boolean) {

        sp(ctx).edit().putBoolean(KEY_AUTO_START, enabled).apply()
    }
}
