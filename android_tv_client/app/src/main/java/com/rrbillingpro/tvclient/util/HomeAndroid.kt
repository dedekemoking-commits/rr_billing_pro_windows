package com.rrbillingpro.tvclient.util

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ResolveInfo
import android.util.Log
import com.rrbillingpro.tvclient.permission.PermissionKit

/**
 * Pembantu "kembali ke Home Android asli" (v4.15).
 *
 * Client TV terdaftar sebagai HOME (LockScreenActivity) supaya tombol HOME
 * tidak bisa keluar saat terkunci. Efek sampingnya: setiap fallback ke HOME
 * mendarat di lockscreen RRBilling — padahal setelah promo selesai TV
 * seharusnya kembali ke launcher bawaan TV / input HDMI.
 *
 * Karena app bisa jadi Home default (role holder), intent HOME biasa tetap
 * menunjuk ke RRBilling. Solusinya: start launcher bawaan secara EKSPLISIT
 * (by component) — explicit intent tidak lewat resolusi role/default.
 */
object HomeAndroid {

    private const val TAG = "RRHome"
    private const val PKG = PermissionKit.PKG

    /**
     * Buka launcher bawaan TV (Google TV / vendor). True bila ada target
     * yang berhasil di-start.
     */
    @Suppress("DEPRECATION")
    fun bukaHomeAndroid(ctx: Context): Boolean {
        val homeIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        val semua = try {
            ctx.packageManager.queryIntentActivities(homeIntent, 0)
        } catch (_: Exception) {
            emptyList<ResolveInfo>()
        }
        val kandidat = semua.filter {
            val info = it.activityInfo ?: return@filter false
            info.enabled && info.packageName != PKG
        }
        val pilihan = pilihLauncher(kandidat)
        if (pilihan != null) {
            val info = pilihan.activityInfo
            val intent = Intent(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_HOME)
                .setComponent(ComponentName(info.packageName, info.name))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            try {
                ctx.startActivity(intent)
                Log.i(TAG, "Home Android: ${info.packageName}/${info.name}")
                return true
            } catch (e: Exception) {
                Log.w(TAG, "start eksplisit gagal: ${e.javaClass.simpleName} ${e.message}")
            }
        }
        // Cadangan: intent HOME biasa — hanya aman bila RRBilling BUKAN Home
        // default; kalau tidak, resolve-nya kembali ke lockscreen sendiri
        // (bisa berputar/nyangkut).
        if (PermissionKit.isHomeDefault(ctx)) {
            Log.w(TAG, "tidak ada launcher lain & RRBilling Home default — dibiarkan")
            return false
        }
        return try {
            ctx.startActivity(homeIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Log.i(TAG, "Home Android via intent biasa")
            true
        } catch (e: Exception) {
            Log.w(TAG, "gagal ke Home Android: ${e.message}")
            false
        }
    }

    /** Prioritas: Google TV launcher -> package ber-"launcher" -> pertama. */
    private fun pilihLauncher(daftar: List<ResolveInfo>): ResolveInfo? {
        if (daftar.isEmpty()) return null
        for (pkg in listOf(
            "com.google.android.tvlauncher",
            "com.google.android.apps.tv.launcherx",
        )) {
            daftar.firstOrNull { it.activityInfo.packageName == pkg }?.let { return it }
        }
        daftar.firstOrNull {
            it.activityInfo.packageName.contains("launcher", ignoreCase = true)
        }?.let { return it }
        return daftar.first()
    }
}
