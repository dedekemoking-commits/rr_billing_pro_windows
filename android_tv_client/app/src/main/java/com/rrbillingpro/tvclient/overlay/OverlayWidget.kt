package com.rrbillingpro.tvclient.overlay

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import com.rrbillingpro.tvclient.R
import com.rrbillingpro.tvclient.permission.OverlayPermission
import com.rrbillingpro.tvclient.util.Prefs

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
    private var tvTotal: TextView? = null

    private val density: Float
        get() = context.resources.displayMetrics.density

    private var style: Prefs.OverlayStyle = Prefs.overlayStyle(context)

    val isShowing: Boolean get() = root != null

    fun show(mejaId: String, namaRental: String, totalTagihan: String,
             lunasTotal: String = "", tagihanTotal: String = "") {
        // Overlay sudah tampil (sesi sebelumnya belum di-STOP) -> jangan early
        // return, tapi perbarui isi kartunya. Kalau tidak, kasir yang mengirim
        // START_TIMER untuk sesi baru akan tetap terlihat nama rental & total
        // sesi LAMA di layar pelanggan.
        if (root != null) {
            updateMejaDanRental(mejaId, namaRental)
            updateBill(totalTagihan, lunasTotal, tagihanTotal)
            return
        }
        tryShow(mejaId, namaRental, totalTagihan, lunasTotal, tagihanTotal, attempt = 0)
    }

    private fun updateMejaDanRental(mejaId: String, namaRental: String) {
        mainHandler.post {
            if (mejaId.isNotBlank()) tvMeja?.text = mejaId
            if (namaRental.isNotBlank()) tvRental?.text = namaRental
        }
    }

    /**
     * Isi ulang kartu tanpa menyentuh teks timer — dipakai Main Bebas yang
     * mengubah label meja ("TV 1 · ∞ BEBAS") dan baris total ("... BERJALAN")
     * di luar siklus tagihan biasa.
     */
    fun updateMejaDanTotal(meja: String, total: String, lunas: String, tagihan: String) {
        mainHandler.post {
            if (meja.isNotBlank()) tvMeja?.text = meja
            val t = total.trim()
            tvTotal?.text = t
            tvTotal?.visibility = if (t.isEmpty()) View.GONE else View.VISIBLE
            tvLunas?.visibility = View.GONE
            tvTagihan?.visibility = View.GONE
        }
    }

    /**
     * Terapkan gaya popup dari kasir (action OVERLAY_STYLE).
     *
     * Berlaku live: kartu yang sedang tampil ikut berubah warna, ukuran, dan
     * posisinya — tidak perlu menunggu sesi berikutnya. Nilai disimpan di TV
     * supaya bertahan setelah restart.
     */
    fun applyStyle(st: Prefs.OverlayStyle) {
        style = st
        mainHandler.post {
            root?.background = buildCardBackground()
            root?.let { applyScaleTo(it) }
        }
    }

    /**
     * Bangun latar kartu dari nilai style saat ini.
     *
     * Tidak memakai R.drawable.bg_overlay_card karena warna di situ terkunci di
     * colors.xml — tidak bisa diubah dari kasir tanpa ganti resource.
     */
    private fun buildCardBackground(): GradientDrawable {
        val s = style
        val alpha = (s.alpha.coerceIn(0, 100) * 255 / 100)
        val scale = s.s()
        return GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = s.radius.coerceAtLeast(0) * density * scale
            setColor(Color.argb(alpha, 0x0B, 0x0F, 0x1E))
            setStroke((2 * density * scale).toInt().coerceAtLeast(1),
                runCatching { Color.parseColor(s.accent) }.getOrDefault(Color.parseColor("#00E5FF")))
        }
    }

    /**
     * Perkecil SELURUH isi kartu proporsional terhadap satu faktor skala:
     * padding, ukuran font, radius sudut, dan ketebalan garis pinggir.
     * Kalau hanya kartu yang diperkecil tapi teks tetap sebesar semula,
     * teks justru makin sulit dibaca.
     */
    private fun applyScaleTo(view: View) {
        val s = style
        val sc = s.s()
        val d = density
        val padH = (14 * d * sc).toInt()
        val padV = (8 * d * sc).toInt()
        view.setPadding(padH, padV, padH, padV)
        val lp = (view.layoutParams as? WindowManager.LayoutParams) ?: return
        val yDp = s.posY.coerceIn(0, 60)
        lp.gravity = Gravity.TOP or Gravity.END
        lp.x = (2 * d).toInt()
        lp.y = (yDp * d).toInt()
        // Ukuran font mengikuti skala, dibatasi supaya tetap terbaca dari sofa.
        tvRental?.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f * sc)
        tvMeja?.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f * sc)
        tvTimer?.setTextSize(TypedValue.COMPLEX_UNIT_SP, s.timerSize.coerceIn(12, 48) * sc)
        tvLunas?.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f * sc)
        tvTagihan?.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f * sc)
        tvTotal?.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f * sc)
    }

    /**
     * Tampilkan overlay dengan retry 3× (jeda 1,5 detik) bila wm.addView gagal.
     * ROM ketat seperti TCL kadang menolak addView sekali pada percobaan
     * pertama (izin overlay baru di-grant via AppOps / window manager belum
     * sinkron) — overlay tidak boleh langsung menyerah.
     */
    private fun tryShow(mejaId: String, namaRental: String, totalTagihan: String,
                        lunasTotal: String, tagihanTotal: String, attempt: Int) {
        if (root != null) return
        val view = inflater.inflate(R.layout.overlay_view, null)
        view.keepScreenOn = true
        tvTimer = view.findViewById(R.id.tv_timer)
        tvMeja = view.findViewById(R.id.tv_meja)
        tvRental = view.findViewById(R.id.tv_rental)
        tvLunas = view.findViewById(R.id.tv_lunas)
        tvTagihan = view.findViewById(R.id.tv_tagihan)
        tvTotal = view.findViewById(R.id.tv_total)

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
            // Di-set lagi di applyScaleTo() supaya ikut gaya dari kasir.
            x = dp(2)
            y = dp(style.posY.coerceIn(0, 60))
        }

        try {
            // Latar & skala berasal dari style (bukan drawable statis), supaya
            // transparansi/warna/ukuran bisa diubah dari kasir saat runtime.
            view.background = buildCardBackground()
            applyScaleTo(view)
            wm.addView(view, params)
            root = view
            // Banner pesan kasir (bila sedang tampil) harus tetap paling atas:
            // kartu waktu yang baru di-add di sini jangan sampai menutupinya.
            MessageOverlay.raiseActive()
            Log.i("RRBillingTV", "Overlay tampil (percobaan ${attempt + 1}) alpha=${style.alpha}% " +
                    "scale=${style.scale}% posY=${style.posY}dp")
        } catch (e: Exception) {
            root = null
            if (attempt >= 2) {
                Log.w("RRBillingTV", "Gagal menampilkan overlay setelah 3x: ${e.message} — " +
                        "izin \u201cTampilkan di atas aplikasi lain\u201d belum aktif? " +
                        "(canDrawOverlays=${OverlayPermission.isGranted(context)})")
            } else {
                Log.w("RRBillingTV", "addView gagal (${e.message}) — retry ${attempt + 2}/3")
                mainHandler.postDelayed({
                    tryShow(mejaId, namaRental, totalTagihan, lunasTotal, tagihanTotal, attempt + 1)
                }, 1500L)
            }
        }
    }

    fun updateTimer(hms: String) {
        mainHandler.post { tvTimer?.text = hms }
    }

    fun updateBill(totalTagihan: String, lunasTotal: String = "", tagihanTotal: String = "") {
        mainHandler.post {
            tvTotal?.text = buildTotal(totalTagihan)
            tvTagihan?.text = buildTagihan(tagihanTotal)
            tvLunas?.text = buildLunas(lunasTotal)
            // Sembunyikan baris yang nilainya nol/kosong agar popup ringkas
            tvLunas?.visibility = if (isNonZero(lunasTotal)) View.VISIBLE else View.GONE
            tvTagihan?.visibility = if (isNonZero(tagihanTotal)) View.VISIBLE else View.GONE
            tvTotal?.visibility = if (isNonZero(totalTagihan)) View.VISIBLE else View.GONE
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

    private fun buildTotal(value: String): String =
        if (isNonZero(value)) "${value.trim()}  TOTAL" else ""

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
            tvTotal = null
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
