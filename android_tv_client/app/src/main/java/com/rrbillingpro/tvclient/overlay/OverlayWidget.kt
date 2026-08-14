package com.rrbillingpro.tvclient.overlay

import android.content.Context
import android.graphics.PixelFormat
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import com.rrbillingpro.tvclient.R
import com.rrbillingpro.tvclient.permission.OverlayPermission

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
    private var tvLunas: TextView? = null
    private var tvTagihan: TextView? = null

    val isShowing: Boolean get() = root != null

    fun show(mejaId: String, namaRental: String, totalTagihan: String,
             lunasTotal: String = "", tagihanTotal: String = "") {
        if (root != null) return
        val view = inflater.inflate(R.layout.overlay_view, null)
        tvTimer = view.findViewById(R.id.tv_timer)
        tvMeja = view.findViewById(R.id.tv_meja)
        tvRental = view.findViewById(R.id.tv_rental)
        tvLunas = view.findViewById(R.id.tv_lunas)
        tvTagihan = view.findViewById(R.id.tv_tagihan)

        tvMeja?.text = mejaId
        tvRental?.text = namaRental
        tvTimer?.text = "00:00:00"
        updateBill(totalTagihan, lunasTotal, tagihanTotal)

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
                    "cek izin \u201cTampilkan di atas aplikasi lain\u201d " +
                    "(Settings.canDrawOverlays=${OverlayPermission.isGranted(context)})")
        }
    }

    fun updateTimer(hms: String) {
        mainHandler.post { tvTimer?.text = hms }
    }

    fun updateBill(totalTagihan: String, lunasTotal: String = "", tagihanTotal: String = "") {
        mainHandler.post {
            tvTagihan?.text = buildTagihan(tagihanTotal)
            tvLunas?.text = buildLunas(lunasTotal)
            // Sembunyikan baris yang nilainya nol/kosong agar popup ringkas
            tvLunas?.visibility = if (isNonZero(lunasTotal)) View.VISIBLE else View.GONE
            tvTagihan?.visibility = if (isNonZero(tagihanTotal)) View.VISIBLE else View.GONE
        }
    }

    fun updateRental(namaRental: String) {
        mainHandler.post { tvRental?.text = namaRental }
    }

    private fun isNonZero(value: String): Boolean =
        !value.isNullOrBlank() && value.replace(Regex("[^0-9]"), "").toIntOrNull()?.let { it > 0 } ?: false

    private fun buildLunas(value: String): String =
        if (isNonZero(value)) "${value.trim()}  ✅ LUNAS" else ""

    private fun buildTagihan(value: String): String =
        if (isNonZero(value)) "${value.trim()}  ⏳ TAGIHAN" else ""

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
            tvLunas = null
            tvTagihan = null
        }
    }

    companion object {
        @Deprecated("Gunakan OverlayPermission.isGranted() yang kompatibel semua ROM")
        fun canDrawOverlays(context: Context): Boolean =
            OverlayPermission.isGranted(context)

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
