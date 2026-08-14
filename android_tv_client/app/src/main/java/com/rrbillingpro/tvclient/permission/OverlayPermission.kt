package com.rrbillingpro.tvclient.permission

import android.app.AppOpsManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Process
import android.provider.Settings
import android.util.Log

/**
 * Pemeriksa & peminta izin overlay (SYSTEM_ALERT_WINDOW) yang kompatibel
 * dengan SEMUA merek TV Android (Google TV, TCL, Hisense, Samsung, Xiaomi,
 * knock-off STB, dll).
 *
 * `Settings.canDrawOverlays()` pada beberapa ROM tidak sinkron dengan
 * AppOps — nilainya tetap false walaupun toggle "Tampilkan di atas aplikasi
 * lain" sudah ON. Jadi kita cek juga AppOps langsung; jika AppOps mengizinkan,
 * `wm.addView()` pasti diterima dan overlay tampil.
 */
object OverlayPermission {

    private const val TAG = "OverlayPermission"

    /**
     * true bila sistem benar-benar akan membolehkan window overlay.
     * Kompatibel ke bawah: minSdk 24 (AppOpsManager tersedia sejak API 19).
     */
    fun isGranted(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        if (Settings.canDrawOverlays(context)) return true

        val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = appOps.checkOpNoThrow(
            AppOpsManager.OPSTR_SYSTEM_ALERT_WINDOW,
            Process.myUid(),
            context.packageName,
        )
        return mode == AppOpsManager.MODE_ALLOWED || mode == AppOpsManager.MODE_DEFAULT
    }

    /**
     * Buka halaman izin overlay. Rantai 3 fallback supaya tidak pernah
     * crash (ActivityNotFoundException) di ROM mana pun:
     *  1. ACTION_MANAGE_OVERLAY_PERMISSION + package URI (jalur normal)
     *  2. ACTION_MANAGE_OVERLAY_PERMISSION tanpa URI (ROM nakal)
     *  3. Daftar semua aplikasi (user cari manual: Izin → Tampilkan di atas)
     */
    fun request(context: Context) {
        try {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:${context.packageName}"),
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            Log.i(TAG, "request: ACTION_MANAGE_OVERLAY_PERMISSION (package)")
            return
        } catch (e: Exception) {
            Log.w(TAG, "request: paket gagal (${e.message}), coba tanpa URI")
        }
        try {
            val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            Log.i(TAG, "request: ACTION_MANAGE_OVERLAY_PERMISSION (tanpa URI)")
            return
        } catch (e: Exception) {
            Log.w(TAG, "request: tanpa URI gagal (${e.message}), coba daftar aplikasi")
        }
        try {
            val intent = Intent(Settings.ACTION_MANAGE_APPLICATIONS_SETTINGS)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            Log.i(TAG, "request: ACTION_MANAGE_APPLICATIONS_SETTINGS")
        } catch (e: ActivityNotFoundException) {
            Log.e(TAG, "request: tidak ada halaman izin sama sekali: ${e.message}")
        }
    }

    /**
     * Pesan panduan universal, dipakai saat izin BELUM diberikan.
     */
    fun guideText(): String =
        "Izin overlay BELUM aktif — popup waktu & PIN tidak akan muncul.\n" +
            "Pengaturan → Aplikasi → RRBillingTV → Izin → " +
            "\"Tampilkan di atas aplikasi lain\" (Allow/On).\n" +
            "Jika sudah diizinkan tapi masih merah: Paksa Berhenti → buka ulang, " +
            "atau restart TV (cache izin di banyak TV tidak langsung disinkronkan)."
}