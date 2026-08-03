package com.rrbillingpro.tvclient.util

import android.content.Context
import android.content.SharedPreferences

object Prefs {
    private const val FILE = "rr_tv_client"
    private const val KEY_HOST = "server_host"
    private const val KEY_PORT = "server_port"
    private const val KEY_MEJA = "meja_id"
    private const val KEY_AUTO_START = "auto_start"

    private fun sp(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun host(ctx: Context): String = sp(ctx).getString(KEY_HOST, "192.168.1.100") ?: "192.168.1.100"

    fun port(ctx: Context): Int = sp(ctx).getInt(KEY_PORT, 8080)

    fun mejaId(ctx: Context): String = sp(ctx).getString(KEY_MEJA, "TV 1") ?: "TV 1"

    fun autoStart(ctx: Context): Boolean = sp(ctx).getBoolean(KEY_AUTO_START, false)

    fun save(ctx: Context, host: String, port: Int, mejaId: String, autoStart: Boolean) {
        sp(ctx).edit()
            .putString(KEY_HOST, host.trim())
            .putInt(KEY_PORT, port)
            .putString(KEY_MEJA, mejaId.trim())
            .putBoolean(KEY_AUTO_START, autoStart)
            .apply()
    }

    fun saveAutoStart(ctx: Context, enabled: Boolean) {
        sp(ctx).edit().putBoolean(KEY_AUTO_START, enabled).apply()
    }
}
