package com.rrbillingpro.tvclient.overlay

import android.content.Context
import android.graphics.PixelFormat
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import com.rrbillingpro.tvclient.R

/**
 * Floating Overlay Widget (sudut kanan atas) — dibangun dengan WindowManager
 * TYPE_APPLICATION_OVERLAY. Non-focusable + touch pass-through sehingga tidak
 * mengganggu gameplay. Teks countdown berwarna neon.
 */
class OverlayWidget(private val context: Context) {

    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val inflater = LayoutInflater.from(context)
    private val mainHandler = Handler(Looper.getMainLooper())

    private var root: View? = null
    private var tvTimer: TextView? = null
    private var tvMeja: TextView? = null
    private var tvRental: TextView? = null
    private var tvTagihan: TextView? = null

    val isShowing: Boolean get() = root != null

    fun show(mejaId: String, namaRental: String, totalTagihan: String) {
        if (root != null) return
        val view = inflater.inflate(R.layout.overlay_view, null)
        tvTimer = view.findViewById(R.id.tv_timer)
        tvMeja = view.findViewById(R.id.tv_meja)
        tvRental = view.findViewById(R.id.tv_rental)
        tvTagihan = view.findViewById(R.id.tv_tagihan)

        tvMeja?.text = mejaId
        tvRental?.text = namaRental
        tvTagihan?.text = totalTagihan
        tvTimer?.text = "00:00:00"

        val type = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            flags,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = dp(12)
            y = dp(12)
        }

        try {
            wm.addView(view, params)
            root = view
        } catch (e: Exception) {
            root = null
            Log.w("RRBillingTV", "Gagal menampilkan overlay: ${e.message} — " +
                    "cek izin Display over other apps")
        }
    }

    fun updateTimer(hms: String) {
        mainHandler.post { tvTimer?.text = hms }
    }

    fun updateBill(totalTagihan: String) {
        mainHandler.post { tvTagihan?.text = totalTagihan }
    }

    fun hide() {
        val view = root ?: return
        mainHandler.post {
            try {
                wm.removeView(view)
            } catch (_: Exception) {
            }
            root = null
            tvTimer = null
            tvMeja = null
            tvRental = null
            tvTagihan = null
        }
    }

    companion object {
        fun canDrawOverlays(context: Context): Boolean =
            Settings.canDrawOverlays(context)

        fun formatHms(seconds: Int): String {
            val s = if (seconds < 0) 0 else seconds
            val h = s / 3600
            val m = (s % 3600) / 60
            val sec = s % 60
            return String.format("%02d:%02d:%02d", h, m, sec)
        }
    }

    private fun dp(value: Int): Int =
        (value * context.resources.displayMetrics.density).toInt()
}
