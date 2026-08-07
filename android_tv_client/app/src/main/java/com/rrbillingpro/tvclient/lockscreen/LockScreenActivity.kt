package com.rrbillingpro.tvclient.lockscreen

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import com.rrbillingpro.tvclient.R
import com.rrbillingpro.tvclient.model.BillLine
import com.rrbillingpro.tvclient.model.LockDetail
import com.rrbillingpro.tvclient.overlay.OverlayWidget
import com.rrbillingpro.tvclient.service.TvOverlayService
import okhttp3.OkHttpClient
import okhttp3.Request

/**
 * Lockscreen fullscreen:
 *  - Menampilkan logo, nama meja, sisa waktu (00:00:00) dan rincian tagihan.
 *  - Memblokir tombol BACK / HOME / APP_SWITCH / MENU selama terkunci.
 *  - Terdaftar sebagai HOME launcher -> tombol HOME tidak bisa keluar dari lock
 *    (unlock hanya dari kasir lewat pesan UNLOCK_SCREEN).
 *  - Saat TIDAK terkunci, aktivitas ini langsung kembali ke aplikasi di bawahnya
 *    (moveTaskToBack) supaya HOME tidak mengganggu game.
 */
class LockScreenActivity : Activity(), TvOverlayService.StateListener {

    private val TAG = "LockScreenActivity"
    private var locked = false
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_lock_screen)

        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        hideSystemBars()

        TvOverlayService.instance?.let { svc ->
            locked = svc.isLocked
            svc.addListener(this)
            render(svc.currentLockDetail)
        }

        if (!locked) {
            // Tidak ada sesi terkunci -> kembali ke aplikasi di bawah (game).
            moveTaskToBack(true)
            finish()
        }
    }

    override fun onResume() {
        super.onResume()
        hideSystemBars()
        val svc = TvOverlayService.instance
        if (svc != null) {
            locked = svc.isLocked
            render(svc.currentLockDetail)
            if (!locked) {
                moveTaskToBack(true)
                finish()
            }
        }
    }

    override fun onDestroy() {
        TvOverlayService.instance?.removeListener(this)
        super.onDestroy()
    }

    private fun render(detail: LockDetail?) {
        val d = detail ?: LockDetail("MEJA", "-", "Rp 0", "Rp 0")
        findViewById<TextView>(R.id.tv_meja).text = d.meja
        findViewById<TextView>(R.id.tv_timer).text = "00:00:00"

        loadLogo(d.logoUrl)

        val container = findViewById<LinearLayout>(R.id.ll_bill_rows)
        container.removeAllViews()

        // Sewa: "1 Jam + 2 Jam = Rp 30.000" — warna hijau jika LUNAS, merah jika TAGIHAN
        val sewaText = if (d.sewaHarga.isNotBlank()) "${d.sewa} = ${d.sewaHarga}" else d.sewa
        addBillRow(container, "Sewa", sewaText, bold = false, lunas = d.sewaLunas)

        if (d.makanan.isNotEmpty()) {
            addBillHeader(container, "Makanan")
            d.makanan.forEach { addBillRow(container, it.item, it.harga, lunas = it.lunas) }
        }
        if (d.minuman.isNotEmpty()) {
            addBillHeader(container, "Minuman")
            d.minuman.forEach { addBillRow(container, it.item, it.harga, lunas = it.lunas) }
        }
        if (d.makanan.isEmpty() && d.minuman.isEmpty()) {
            addBillRow(container, "Makanan & Minuman", d.fnb, lunas = true)
        }

        addDivider(container)
        addBillRow(container, "TOTAL", d.total, bold = true)

        // Rincian LUNAS / TAGIHAN berwarna (jika server mengirim keduanya)
        if (d.lunasTotal.isNotBlank()) {
            addBillRow(container, "LUNAS", d.lunasTotal, bold = true, lunas = true)
        }
        if (d.tagihanTotal.isNotBlank()) {
            addBillRow(container, "TAGIHAN", d.tagihanTotal, bold = true, lunas = false)
        }
    }

    private fun addBillHeader(parent: LinearLayout, text: String) {
        val tv = TextView(this).apply {
            this.text = text
            setTextColor(getColor(R.color.neon_cyan))
            textSize = 14f
            setTypeface(typeface, Typeface.BOLD)
        }
        parent.addView(tv, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(10)
        })
    }

    private fun addBillRow(parent: LinearLayout, label: String, value: String,
                           bold: Boolean = false, lunas: Boolean = true) {
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(TextView(this).apply {
            text = label
            setTextColor(getColor(R.color.text_muted))
            textSize = 15f
            if (bold) setTypeface(typeface, Typeface.BOLD)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        row.addView(TextView(this).apply {
            // Baris rincian item: tampilkan status LUNAS/TAGIHAN berwarna setelah harga
            text = value + if (bold) "" else if (lunas) "  ✅ LUNAS" else "  ⏳ TAGIHAN"
            setTextColor(getColor(if (bold) R.color.neon_yellow else if (lunas) R.color.neon_green else R.color.neon_red))
            textSize = 15f
            if (bold) setTypeface(typeface, Typeface.BOLD)
        })
        parent.addView(row, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(if (parent.childCount == 0) 0 else 6)
        })
    }

    private fun addDivider(parent: LinearLayout) {
        val div = View(this).apply {
            setBackgroundColor(getColor(R.color.neon_cyan))
        }
        parent.addView(div, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(1)).apply {
            topMargin = dp(10)
            bottomMargin = dp(6)
        })
    }

    /**
     * Logo lock screen: pakai logo_url dari server (bisa diganti kasir via
     * tombol "Ganti Logo Lock"). Gagal/kosong -> fallback ke logo bawaan APK
     * atau logo terakhir yang berhasil diunduh (cache).
     */
    private fun loadLogo(url: String) {
        val iv = findViewById<ImageView>(R.id.iv_logo) ?: return
        val cached = cachedLogo
        if (url.isBlank()) {
            if (cached != null) {
                iv.setImageBitmap(cached)
            } else {
                iv.setImageResource(R.drawable.logo_lock)
            }
            return
        }
        Thread {
            try {
                val client = OkHttpClient()
                val req = Request.Builder().url(url).build()
                client.newCall(req).execute().use { resp ->
                    if (resp.isSuccessful) {
                        val bytes = resp.body?.bytes()
                        val bmp = decodeSampled(bytes)
                        if (bmp != null) {
                            cachedLogo = bmp
                            runOnUiThread { iv.setImageBitmap(bmp) }
                        } else {
                            Log.w(TAG, "loadLogo: decode gagal untuk $url")
                        }
                    } else {
                        Log.w(TAG, "loadLogo: HTTP ${resp.code} untuk $url")
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "loadLogo: error $url — ${e.message}")
            }
        }.start()
    }

    /**
     * Decode gambar dengan sampling: ukur dimensi dulu (tanpa alokasi penuh),
     * lalu decode dengan inSampleSize agar bitmap tidak pernah melebihi
     * ~1920px per sisi — mencegah OutOfMemory/crash "Canvas: trying to draw
     * too large bitmap" bila logo yang diupload beresolusi raksasa.
     */
    private fun decodeSampled(bytes: ByteArray?): Bitmap? {
        if (bytes == null || bytes.isEmpty()) return null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (bounds.outWidth / sample > 1920 || bounds.outHeight / sample > 1920) {
            sample *= 2
        }
        return try {
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size,
                BitmapFactory.Options().apply { inSampleSize = sample })
        } catch (_: OutOfMemoryError) {
            Log.w(TAG, "loadLogo: OOM saat decode (${bounds.outWidth}x${bounds.outHeight})")
            null
        }
    }

    private fun dp(v: Int): Int =
        (v * resources.displayMetrics.density).toInt()

    // ── Blokir tombol sistem selama terkunci ────────────────────────────────
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (locked) {
            when (event.keyCode) {
                KeyEvent.KEYCODE_BACK,
                KeyEvent.KEYCODE_HOME,
                KeyEvent.KEYCODE_APP_SWITCH,
                KeyEvent.KEYCODE_MENU -> return true
            }
        }
        return super.dispatchKeyEvent(event)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    // ── Listener dari service (UNLOCK_SCREEN dari kasir) ────────────────────
    override fun onLockChanged(locked: Boolean) {
        runOnUiThread {
            if (!locked) {
                moveTaskToBack(true)
                finish()
            }
        }
    }

    override fun onStatusChanged(connected: Boolean) = Unit

    private fun hideSystemBars() {
        window.decorView.systemUiVisibility =
            (View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    or View.SYSTEM_UI_FLAG_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_STABLE)
    }

    companion object {
        @Volatile
        private var instance: LockScreenActivity? = null

        // Logo terakhir dari server (cache) — dipakai juga saat auto-lock
        // countdown habis sebelum LOCK_SCREEN resmi tiba dari kasir.
        @Volatile
        private var cachedLogo: Bitmap? = null

        fun start(context: Context, detail: LockDetail?) {
            val i = Intent(context, LockScreenActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            if (detail != null) {
                i.putExtra("meja", detail.meja)
                    .putExtra("sewa", detail.sewa)
                    .putExtra("fnb", detail.fnb)
                    .putExtra("total", detail.total)
            }
            context.startActivity(i)
        }

        fun finishInstance() {
            instance?.runOnUiThread { instance?.finish() }
        }

        fun updateDetail(detail: LockDetail?) {
            // Perbarui isi lockscreen yang sudah tampil (dipanggil saat
            // LOCK_SCREEN tiba setelah autoLock dari countdown client).
            val act = instance
            if (act != null) {
                act.runOnUiThread {
                    act.locked = true
                    act.render(detail)
                }
            }
        }
    }

    // Simpan referensi instance untuk finishInstance()
    override fun onStart() {
        super.onStart()
        instance = this
    }

    override fun onStop() {
        if (instance === this) instance = null
        super.onStop()
    }
}
