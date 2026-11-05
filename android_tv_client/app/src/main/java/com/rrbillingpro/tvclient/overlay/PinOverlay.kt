package com.rrbillingpro.tvclient.overlay

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import com.rrbillingpro.tvclient.permission.OverlayPermission
import com.rrbillingpro.tvclient.util.Prefs

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
    private var tvMeja: TextView? = null
    private var tvPin: TextView? = null
    private var tvKet: TextView? = null

    private val density: Float
        get() = context.resources.displayMetrics.density

    private var style: Prefs.OverlayStyle = Prefs.overlayStyle(context)

    val isShowing: Boolean get() = root != null

    fun show(pin: String, mejaId: String = "") {
        if (root != null) hide()
        tryShow(pin, mejaId, attempt = 0)
    }

    /**
     * Ikuti gaya popup yang sama dengan kartu timer (dikirim kasir lewat
     * OVERLAY_STYLE): transparansi, warna aksen, ukuran, dan posisi.
     * Tanpa ini, kartu timer jadi transparan tapi PIN tetap pekat —
     * terlihat tidak konsisten di layar yang sama.
     */
    fun applyStyle(st: Prefs.OverlayStyle) {
        style = st
        mainHandler.post {
            root?.background = buildCardBackground()
            root?.let { applyScaleTo(it) }
        }
    }

    private fun buildCardBackground(): GradientDrawable {
        val s = style
        val alpha = s.alpha.coerceIn(0, 100) * 255 / 100
        val scale = s.s()
        val d = density
        return GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = s.radius.coerceAtLeast(0) * d * scale
            setColor(Color.argb(alpha, 0x0B, 0x0F, 0x1E))
            setStroke((2 * d * scale).toInt().coerceAtLeast(1),
                runCatching { Color.parseColor(s.accent) }.getOrDefault(Color.parseColor("#00E5FF")))
        }
    }

    private fun applyScaleTo(view: View) {
        val s = style
        val sc = s.s()
        val d = density
        val padH = (12 * d * sc).toInt()
        val padV = (9 * d * sc).toInt()
        view.setPadding(padH, padV, padH, padV)
        val lp = view.layoutParams as? WindowManager.LayoutParams ?: return
        lp.gravity = Gravity.TOP or Gravity.START
        lp.x = (2 * d).toInt()
        lp.y = (s.posY.coerceIn(0, 60) * d).toInt()
        tvMeja?.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f * sc)
        tvPin?.setTextSize(TypedValue.COMPLEX_UNIT_SP, 34f * sc)
        tvKet?.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f * sc)
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
        }
        if (mejaId.isNotBlank()) {
            tvMeja = TextView(context).apply {
                text = mejaId
                setTextColor(0xFFFFCC00.toInt())
                typeface = Typeface.DEFAULT_BOLD
            }
            column.addView(tvMeja)
        }
        tvPin = TextView(context).apply {
            text = pin
            setTextColor(0xFFFF3B30.toInt())
            typeface = Typeface.MONOSPACE
            setTypeface(typeface, Typeface.BOLD)
        }
        column.addView(tvPin)
        tvKet = TextView(context).apply {
            text = "PIN untuk Web panggil operator"
            setTextColor(0xFFFFFFFF.toInt())
        }
        column.addView(tvKet)

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
            x = dp(2)
            y = dp(style.posY.coerceIn(0, 60))
        }
        try {
            column.background = buildCardBackground()
            applyScaleTo(column)
            wm.addView(column, params)
            root = column
            Log.i("PinOverlay", "PIN shown for $mejaId (percobaan ${attempt + 1}) " +
                    "alpha=${style.alpha}% scale=${style.scale}%")
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
        tvMeja = null
        tvPin = null
        tvKet = null
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