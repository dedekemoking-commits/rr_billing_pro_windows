package com.rrbillingpro.tvclient.permission

import android.app.AppOpsManager
import android.app.admin.DevicePolicyManager
import android.app.role.RoleManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.os.Process
import android.provider.Settings
import android.util.Log

/**
 * Pemeriksa KELENGKAPAN izin & setting client TV.
 *
 * Semua syarat di sini WAJIB aktif agar client TV bisa:
 *   - terhubung ke server kasir tanpa putus,
 *   - menampilkan popup sisa waktu & PIN (overlay),
 *   - menjalankan lockscreen yang tidak bisa dirok (device owner / home),
 *   - tetap hidup saat TV diam atau berpindah input.
 *
 * Setiap syarat punya:
 *   - statusOk()  -> sudah aktif?
 *   - buka(ctx)   -> arahkan pengguna ke halaman pengaturan yang tepat.
 *
 * Catatan: Android TIDAK mengizinkan app mengaktifkan sendiri developer
 * options / device owner. App hanya bisa mendeteksi + membuka halaman resmi.
 */
object PermissionKit {

    private const val TAG = "PermissionKit"
    const val PKG = "com.rrbillingpro.tvclient"
    const val ADMIN = "$PKG/.KioskAdminReceiver"

    data class Item(
        val key: String,
        val judul: String,
        val keterangan: String,
        val ok: Boolean,
        val manual: Boolean,   // true = tidak bisa diaktifkan otomatis dari app
        val aksi: String = ""   // keterangan tambahan hasil pemeriksaan
    )

    // ── Pemeriksaan individual ─────────────────────────────────────────────

    fun overlayOk(ctx: Context): Boolean = OverlayPermission.isGranted(ctx)

    fun notifOk(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT < 33) return true
        return ctx.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED
    }

    /** Device Owner -> Lock Task mode aktif (kunci total). */
    fun deviceOwnerOk(ctx: Context): Boolean {
        return try {
            val dpm = ctx.getSystemService(Context.DEVICE_POLICY_SERVICE)
                    as DevicePolicyManager
            dpm.isDeviceOwnerApp(PKG)
        } catch (e: Exception) {
            false
        }
    }

    /** Device Admin aktif (minimal). */
    fun deviceAdminOk(ctx: Context): Boolean {
        return try {
            val dpm = ctx.getSystemService(Context.DEVICE_POLICY_SERVICE)
                    as DevicePolicyManager
            dpm.isAdminActive(ComponentName(PKG, PKG + ".KioskAdminReceiver"))
        } catch (e: Exception) {
            false
        }
    }

    /** Battery optimization: diabaikan penghematan? */
    fun batteryIgnored(ctx: Context): Boolean {
        return try {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
            val pm = ctx.getSystemService(Context.POWER_SERVICE) as PowerManager
            pm.isIgnoringBatteryOptimizations(PKG)
        } catch (e: Exception) {
            false
        }
    }

    /** Background usage: boleh jalan di latar belakang (App Standby = ACTIVE)? */
    fun backgroundActive(ctx: Context): Boolean {
        return try {
            val am = ctx.getSystemService(Context.ACTIVITY_SERVICE)
                    as android.app.ActivityManager
            // getApplicationStandbyBucket butuh API 28; untuk Android 7/8 (API
            // 24-27) tidak ada fitur App Standby sehingga dianggap OK.
            if (Build.VERSION.SDK_INT < 28) return true
            val m = android.app.ActivityManager::class.java
                .getMethod("getApplicationStandbyBucket", String::class.java)
            val bucket = (m.invoke(am, PKG) as? Int) ?: return true
            bucket <= 10   // 10 == ACTIVE, 20 == WORKING_SET, 30+ == limited
        } catch (e: Exception) {
            true   // tidak bisa dibaca -> anggap OK (tidak membatasi)
        }
    }

    /** Opsi developer aktif? */
    fun developerOptionsOn(ctx: Context): Boolean {
        return try {
            Settings.Global.getInt(
                ctx.contentResolver,
                Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) == 1
        } catch (e: Exception) {
            false
        }
    }

    /** Stay awake saat charging? */
    fun stayAwakeOn(ctx: Context): Boolean {
        return try {
            Settings.Global.getInt(
                ctx.contentResolver, "stay_on_while_plugged_in", 0) != 0
        } catch (e: Exception) {
            false
        }
    }

    /**
     * App ini jadi Home default?
     *
     * PENTING: di Android TV (role-based HOME), `resolveActivity()` tidak
     * mengikuti role holder sehingga selalu mengembalikan launcher bawaan
     * walau user sudah memilih RR Billing TV. Sumber benar adalah
     * RoleManager (Android 10+). resolveActivity hanya dipakai sebagai
     * cadangan untuk Android 9 ke bawah.
     */
    fun isHomeDefault(ctx: Context): Boolean {
        // 1) Cara resmi Android 10+ (role holder). getRoleHolders() adalah API
        //    tersembunyi, jadi pakai isRoleHeld() yang publik.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                val rm = ctx.getSystemService(Context.ROLE_SERVICE) as RoleManager
                if (rm.isRoleAvailable(RoleManager.ROLE_HOME) &&
                    rm.isRoleHeld(RoleManager.ROLE_HOME)) return true
            } catch (e: Exception) {
                Log.w(TAG, "RoleManager gagal: ${e.message}")
            }
        }
        // 2) Cadangan: activity manager (Android 9 ke bawah).
        return try {
            val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            val daftar = ctx.packageManager.queryIntentActivities(
                intent, PackageManager.MATCH_DEFAULT_ONLY)
            daftar.any { it.activityInfo?.packageName == PKG }
        } catch (e: Exception) {
            false
        }
    }

    // ── Pemeriksaan gabungan ───────────────────────────────────────────────

    fun periksaSemua(ctx: Context): List<Item> {
        val owner = deviceOwnerOk(ctx)
        val home = isHomeDefault(ctx)
        val dev = developerOptionsOn(ctx)
        val stay = stayAwakeOn(ctx)
        val batt = batteryIgnored(ctx)
        val bg = backgroundActive(ctx)
        val ovl = overlayOk(ctx)
        val notif = notifOk(ctx)

        return listOf(
            Item("overlay", "Izin Tampilkan di Atas Aplikasi Lain",
                "Agar popup sisa waktu, PIN operator, dan QR member muncul.",
                ovl, false,
                if (ovl) "Tampilkan di atas aplikasi lain = ON"
                else "Belum aktif -> TV: Izin -> Tampilkan di atas aplikasi lain"),
            Item("notif", "Izin Notifikasi",
                "Agar service TV tidak dibunuh sistem Android.",
                notif, false,
                if (notif) "Notifikasi = diizinkan" else "Belum diizinkan -> Izin -> Notifikasi"),
            Item("deviceowner", "Device Admin / Device Owner",
                "Agar lockscreen tidak bisa dirok dengan tombol remote.",
                owner, true,
                if (owner) "Device Owner aktif (Lock Task)"
                else "Belum -> biasanya TV belum boleh punya akun Google"),
            Item("home", "Jadikan Home Default",
                "Agar tombol HOME selalu kembali ke lockscreen/billing.",
                home, true,
                if (home) "Home = RR Billing TV" else "Home masih launcher bawaan TV"),
            Item("dev", "Opsi Developer",
                "Syarat ADB debugging & beberapa izin lanjutan.",
                dev, true,
                if (dev) "Developer options aktif" else "Developer options belum aktif"),
            Item("stayawake", "Stay Awake (Tetap Nyala)",
                "Agar TV & service tidak tidur saat sedang disewa.",
                stay, true,
                if (stay) "Stay awake aktif" else "Stay awake belum aktif"),
            Item("battery", "Battery Optimization",
                "Agar aplikasi tidak dihinakan saat TV diam.",
                batt, true,
                if (batt) "Diabaikan penghematan"
                else "Masih ikut penghematan -> Baterai -> Jangan izinkan"),
            Item("background", "Background Usage (App Standby)",
                "Agar aplikasi tetap hidup di latar belakang.",
                bg, true,
                if (bg) "App Standby = active" else "App Standby dibatasi -> Battery -> Unrestricted")
        )
    }

    /** Ringkasan: (siap, belum). */
    fun ringkas(items: List<Item>): Pair<Int, Int> {
        val ok = items.count { it.ok }
        return ok to (items.size - ok)
    }

    /** Syarat wajib keras (harus aktif agar sistem jalan). */
    fun siapSemua(ctx: Context): Boolean {
        val items = periksaSemua(ctx)
        val wajib = setOf("overlay", "notif", "deviceowner")
        return items.filter { it.key in wajib }.all { it.ok }
    }

    fun catatKeServer(ctx: Context, items: List<Item>) {
        val ringkas = items.joinToString(", ") { "${it.key}=${if (it.ok) "OK" else "BELUM"}" }
        Log.i(TAG, "Kelengkapan izin: $ringkas")
    }

    // ── Pembuka halaman pengaturan ─────────────────────────────────────────

    private fun start(ctx: Context, intent: Intent): Boolean {
        return try {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ctx.startActivity(intent)
            true
        } catch (e: Exception) {
            false
        }
    }

    private fun appDetail(ctx: Context): Boolean = start(
        ctx, Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
            .setData(Uri.parse("package:$PKG")))

    fun buka(ctx: Context, key: String): Boolean {
        when (key) {
            // 1) Izin overlay - paling sering dipakai.
            "overlay" -> {
                OverlayPermission.request(ctx)
                return true
            }

            // 2) Notifikasi.
            "notif" -> {
                if (Build.VERSION.SDK_INT >= 33) {
                    try {
                        ctx.startActivity(
                            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                                .putExtra(Settings.EXTRA_APP_PACKAGE, PKG)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        )
                        return true
                    } catch (e: Exception) {
                    }
                }
                return appDetail(ctx)
            }

            // 3) Device owner - butuh ADB, arahkan ke pengaturan keamanan.
            "deviceowner" -> {
                if (start(ctx, Intent(Settings.ACTION_SECURITY_SETTINGS))) return true
                return appDetail(ctx)
            }

            // 4) Home default - pemilih aplikasi default.
            "home" -> {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    if (start(ctx, Intent("android.settings.MANAGE_HOME_APP_SETTINGS"))) {
                        return true
                    }
                    if (start(ctx, Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS))) {
                        return true
                    }
                }
                if (start(ctx, Intent(Intent.ACTION_MAIN)
                        .addCategory(Intent.CATEGORY_HOME))) return true
                return start(ctx, Intent(Settings.ACTION_SETTINGS))
            }

            // 5) Developer options.
            "dev" -> return start(ctx, Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS))

            // 6) Stay awake / battery optimization.
            "stayawake", "battery" -> {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    if (start(ctx, Intent(
                            Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))) {
                        return true
                    }
                }
                return appDetail(ctx)
            }

            // 7) Background usage / app standby.
            "background" -> {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    if (start(ctx, Intent("android.settings.APP_STANDBY_SETTINGS"))) {
                        return true
                    }
                    if (start(ctx, Intent(
                            Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))) {
                        return true
                    }
                }
                return appDetail(ctx)
            }

            // Default: detail aplikasi.
            else -> return appDetail(ctx)
        }
    }

    /** Ringkasan singkat untuk notifikasi service. */
    fun ringkasTeks(ctx: Context): String {
        val items = periksaSemua(ctx)
        val (ok, belum) = ringkas(items)
        return "Izin siap $ok/${items.size}" +
                if (belum > 0) " — $belum perlu diatur" else " — semua siap"
    }
}
