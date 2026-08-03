package com.rrbillingpro.tvclient

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.rrbillingpro.tvclient.service.TvOverlayService
import com.rrbillingpro.tvclient.util.Prefs

/**
 * Autostart service saat STB dinyalakan (opsional — aktif jika auto_start true).
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action == Intent.ACTION_BOOT_COMPLETED || action == "android.intent.action.QUICKBOOT_POWERON") {
            if (Prefs.autoStart(context)) {
                TvOverlayService.start(context)
            }
        }
    }
}
