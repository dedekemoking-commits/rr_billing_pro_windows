package com.rrbillingpro.tvclient

import android.app.admin.DeviceAdminReceiver
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Penerima device admin. Aktivasi (satu kali, via ADB — butuh tanpa akun Google):
 *   adb shell dpm set-device-owner com.rrbillingpro.tvclient/.KioskAdminReceiver
 *
 * Setelah jadi device owner, LockScreenActivity bisa masuk Lock Task mode
 * (startLockTask) sehingga tombol HOME / recent / notifikasi / global action
 * tidak berfungsi saat TV terkunci.
 *
 * Penghapusan: adb shell dpm remove-active-admin com.rrbillingpro.tvclient/.KioskAdminReceiver
 */
class KioskAdminReceiver : DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        Log.i("KioskAdminReceiver", "Device admin enabled")
    }

    override fun onDisableRequested(context: Context, intent: Intent): CharSequence? {
        return "Menonaktifkan admin melemahkan proteksi lockscreen TV. Lanjutkan?"
    }

    companion object {
        fun isDeviceOwner(context: Context): Boolean = try {
            val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
            dpm.isDeviceOwnerApp(context.packageName)
        } catch (_: Exception) {
            false
        }

        fun allowSelfLockTask(context: Context) {
            try {
                val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
                val comp = ComponentName(context, KioskAdminReceiver::class.java)
                dpm.setLockTaskPackages(comp, arrayOf(context.packageName))
            } catch (e: Exception) {
                Log.w("KioskAdminReceiver", "setLockTaskPackages gagal: ${e.message}")
            }
        }
    }
}
