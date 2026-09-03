package com.rrbillingpro.tvclient.overlay

import android.content.Context
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import com.rrbillingpro.tvclient.permission.OverlayPermission

/**
 * Overlay PIN "Panggil Operator/Kasir" — pojok KIRI atas layar TV.
 *
 * Ditampilkan saat pelanggan scan QR (server kirim action SHOW_PIN) dan
 * disembunyikan saat sesi selesai / PIN terpakai / user masuk web
 * (action HIDE_PIN). Terpisah dari OverlayWidget (sisa waktu, kanan atas).
 */
class PinOverlay(private val context: Context) {

    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val mainHandler = Handler(Looper.getMainLooper())

    private var root: View? = null

    val isShowing: Boolean get() = root != null

    fun show(pin: String, mejaId: String = "") {
        if (root != null) hide()
        tryShow(pin, mejaId, attempt = 0)
    }

    /**
     * Tampilkan overlay PIN dengan retry 3× (jeda 1,5 detik) bila wm.addView
     * gagal — ROM ketat seperti TCL kadang menolak addView di percobaan
     * pertama (izin overlay / sinkronisasi window manager belum siap).
     */
    private fun tryShow(pin: String, mejaId: String, attempt: Int) {
        if (root != null) return
        val column = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(8), dp(6), dp(8), dp(6))
            setBackgroundColor(0x00000000.toInt())
        }
        if (mejaId.isNotBlank()) {
            column.addView(TextView(context).apply {
                text = mejaId
                setTextColor(0xFFFFCC00.toInt())
                textSize = 14f
                typeface = Typeface.DEFAULT_BOLD
            })
        }
        column.addView(TextView(context).apply {
            text = pin
            setTextColor(0xFFFF3B30.toInt())
            textSize = 34f
            typeface = Typeface.MONOSPACE
            setTypeface(typeface, Typeface.BOLD)
        })
        column.addView(TextView(context).apply {
            text = "PIN untuk Web panggil operator"
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 13f
            setPadding(0, dp(2), 0, 0)
        })

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
            gravity = Gravity.TOP or Gravity.START
            x = dp(12)
            y = dp(12)
        }
        try {
            wm.addView(column, params)
            root = column
            Log.i("PinOverlay", "PIN shown for $mejaId (percobaan ${attempt + 1})")
        } catch (e: Exception) {
            root = null
            if (attempt >= 2) {
                Log.w("PinOverlay", "Gagal menampilkan PIN setelah 3x: ${e.message} — cek izin overlay")
            } else {
                Log.w("PinOverlay", "Gagal menampilkan PIN (${e.message}) — retry ${attempt + 2}/3")
                mainHandler.postDelayed({
                    tryShow(pin, mejaId, attempt + 1)
                }, 1500L)
            }
        }
    }

    fun hide() {
        val view = root ?: return
        // Hapus referensi SINKRON: kalau show() dipanggil sebelum lambda
        // sempat jalan, view lama tetap dihapus tapi root tidak boleh
        // menunjuk ke view basi (kalau tidak, HIDE berikutnya diabaikan).
        root = null
        mainHandler.post {
            try {
                wm.removeView(view)
                Log.i("PinOverlay", "PIN hidden")
            } catch (e: Exception) {
                Log.w("PinOverlay", "Gagal menyembunyikan PIN: ${e.message}")
            }
        }
    }

    companion object {
        @Deprecated("Gunakan OverlayPermission.isGranted() yang kompatibel semua ROM")
        fun canDrawOverlays(context: Context): Boolean =
            OverlayPermission.isGranted(context)
    }

    private fun dp(value: Int): Int =
        (value * context.resources.displayMetrics.density).toInt()
}