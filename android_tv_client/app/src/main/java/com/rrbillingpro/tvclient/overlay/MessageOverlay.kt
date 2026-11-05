package com.rrbillingpro.tvclient.overlay

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.text.TextUtils
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import com.rrbillingpro.tvclient.util.Prefs

/**
 * Banner pesan singkat dari kasir (action SHOW_MESSAGE, v4.17) — mis.
 * "Mohon Jangan Ribut".
 *
 * Ditaruh di posisi yang SAMA dengan kartu waktu sesi (kanan atas, y dari
 * gaya overlay kasir) sehingga saat tampil banner MENIMPA kartu waktu.
 * (v4.20) Sebelumnya di kiri atas — menutupi area popup PIN.
 *
 * Overlay transparan ala notifikasi: non-focusable + non-touchable sehingga
 * game/HDMI di belakangnya tetap bisa dimainkan. Hilang sendiri setelah
 * `durasi` detik; pesan baru yang datang mengganti pesan lama (timer
 * di-reset). Gaya kartu disamakan dengan overlay lain (latar gelap
 * transparan + garis aksen cyan).
 */
class MessageOverlay(private val context: Context) {

    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val mainHandler = Handler(Looper.getMainLooper())

    private var root: View? = null
    private var teksView: TextView? = null
    private var dismissRunnable: Runnable? = null
    private var params: WindowManager.LayoutParams? = null

    private val density: Float
        get() = context.resources.displayMetrics.density

    val isShowing: Boolean get() = root != null

    /** Tampilkan (atau ganti) banner. `durasiDetik` dijepit 3-300 dtk. */
    fun show(pesan: String, durasiDetik: Int) {
        val durasi = durasiDetik.coerceIn(3, 300).toLong() * 1000L
        mainHandler.post {
            dismissRunnable?.let { mainHandler.removeCallbacks(it) }
            val ada = teksView
            if (ada != null) {
                ada.text = pesan
                // Popup waktu bisa saja di-add ulang SETELAH banner ini,
                // jadi tumpukannya kini di bawah — naikkan lagi.
                raiseNow()
            } else {
                tryShow(pesan, attempt = 0)
            }
            val run = Runnable { hide() }
            dismissRunnable = run
            mainHandler.postDelayed(run, durasi)
            Log.i(TAG, "pesan tampil ${durasi / 1000} dtk: ${pesan.take(60)}")
        }
    }

    /**
     * Retry 3x (jeda 1,5 dtk) bila wm.addView gagal — ROM ketat seperti TCL
     * kadang menolak addView percobaan pertama (izin overlay / sinkronisasi
     * window manager belum siap), sama seperti penanganan PinOverlay.
     */
    private fun tryShow(pesan: String, attempt: Int) {
        if (root != null) return
        val layar = context.resources.displayMetrics.widthPixels
        val tv = TextView(context).apply {
            text = pesan
            setTextColor(Color.WHITE)
            typeface = Typeface.DEFAULT_BOLD
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 24f)
            gravity = Gravity.CENTER
            maxLines = 3
            ellipsize = TextUtils.TruncateAt.END
            maxWidth = (layar * 0.7f).toInt()
            val padH = dp(30)
            val padV = dp(16)
            setPadding(padH, padV, padH, padV)
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = 20f * density
                setColor(Color.argb(215, 0x0B, 0x0F, 0x1E))
                setStroke(dp(2).coerceAtLeast(1), Color.parseColor("#00E5FF"))
            }
        }

        // minSdk 26 = Android O, jadi TYPE_APPLICATION_OVERLAY selalu tersedia.
        val flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
        val type = WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        // v4.20: posisi mengikuti kartu waktu sesi (kanan atas) supaya banner
        // MENIMPA kartu waktu saat tampil, bukan di kiri atas area popup PIN.
        val st = Prefs.overlayStyle(context)
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            flags,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = dp(2)
            y = dp(st.posY.coerceIn(0, 60))
        }
        try {
            wm.addView(tv, params)
            root = tv
            teksView = tv
            this.params = params
            active = this
            Log.i(TAG, "banner shown (percobaan ${attempt + 1})")
        } catch (e: Exception) {
            root = null
            teksView = null
            if (attempt >= 2) {
                Log.w(TAG, "Gagal menampilkan banner setelah 3x: ${e.message} — cek izin overlay")
            } else {
                Log.w(TAG, "Gagal menampilkan banner (${e.message}) — retry ${attempt + 2}/3")
                mainHandler.postDelayed({ tryShow(pesan, attempt + 1) }, 1500L)
            }
        }
    }

    /**
     * Paksa window banner kembali PALING ATAS dari overlay lain (kartu waktu
     * dsb). WindowManager tidak punya API raise untuk TYPE_APPLICATION_OVERLAY
     * — urutan tumpukan = urutan addView — jadi remove lalu add ulang.
     * Dipanggil dari thread main (show()) atau via raise().
     */
    private fun raiseNow() {
        val view = root ?: return
        val p = params ?: return
        // Ikuti gaya overlay terbaru — kasir bisa mengubah posY saat banner
        // masih tampil, dan posisi banner harus tetap pas menimpa kartu waktu.
        p.x = dp(2)
        p.y = dp(Prefs.overlayStyle(context).posY.coerceIn(0, 60))
        try {
            wm.removeView(view)
            wm.addView(view, p)
            Log.i(TAG, "banner di-raise di atas overlay lain")
        } catch (e: Exception) {
            Log.w(TAG, "Gagal raise banner: ${e.message}")
        }
    }

    /** Versi aman dari thread mana pun. */
    fun raise() {
        mainHandler.post { raiseNow() }
    }

    fun hide() {
        val view = root ?: return
        // Hapus referensi SINKRON — show() berikutnya tidak boleh melihat
        // view basi yang sedang dihapus.
        root = null
        teksView = null
        params = null
        if (active === this) active = null
        dismissRunnable?.let { mainHandler.removeCallbacks(it) }
        dismissRunnable = null
        mainHandler.post {
            try {
                wm.removeView(view)
                Log.i(TAG, "banner hidden")
            } catch (e: Exception) {
                Log.w(TAG, "Gagal menyembunyikan banner: ${e.message}")
            }
        }
    }

    private fun dp(value: Int): Int = (value * density).toInt()

    companion object {
        private const val TAG = "MessageOverlay"

        @Volatile
        private var active: MessageOverlay? = null

        /**
         * Dipanggil overlay lain (mis. kartu waktu) SETELAH ia selesai
         * addView, supaya banner pesan yang sedang tampil kembali menumpuk
         * di atasnya — kartu waktu tidak boleh menutupi pesan kasir.
         */
        fun raiseActive() {
            active?.raise()
        }
    }
}
