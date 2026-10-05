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
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import com.rrbillingpro.tvclient.R
import com.rrbillingpro.tvclient.model.BillLine
import com.rrbillingpro.tvclient.model.LockDetail
import com.rrbillingpro.tvclient.overlay.OverlayWidget
import com.rrbillingpro.tvclient.service.TvOverlayService
import com.rrbillingpro.tvclient.util.Prefs
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
    private var bgPlayer: ExoPlayer? = null
    private var bgTexture: android.view.TextureView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        instance = this
        setContentView(R.layout.activity_lock_screen)

        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        hideSystemBars()

        applyLockBg(Prefs.lockBgUrl(this))

        TvOverlayService.instance?.let { svc ->
            locked = svc.isLocked
            svc.addListener(this)
            render(svc.currentLockDetail)
        }
        // Tabrak state layar mati-dan-nyala: jika service belum siap, pakai Prefs.
        if (!locked && Prefs.isLocked(this)) {
            locked = true
            render(Prefs.lockDetail(this))
        }

        if (!locked) {
            // Tidak ada sesi terkunci -> kembali ke aplikasi di bawah (game).
            moveTaskToBack(true)
            finish()
        } else {
            enterLockTaskMode()
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
                return
            }
        } else if (Prefs.isLocked(this)) {
            locked = true
            render(Prefs.lockDetail(this))
        } else {
            moveTaskToBack(true)
            finish()
            return
        }
        if (locked) enterLockTaskMode()
    }

    override fun onDestroy() {
        TvOverlayService.instance?.removeListener(this)
        exitLockTaskMode()
        releaseBgPlayer()
        super.onDestroy()
    }

    // ── Background gambar bergerak (MP4 loop dari kasir) ────────────────────
    private fun applyLockBg(url: String) {
        val box = findViewById<android.widget.FrameLayout>(R.id.fl_lock_video) ?: return
        releaseBgPlayer()
        if (url.isBlank()) {
            bgTexture?.visibility = View.GONE
            showPanelPesan("Kasir belum mengatur gambar bergerak")
            Log.i(TAG, "Background lockscreen: pakai latar polos (tidak ada video)")
            return
        }
        try {
            val http = OkHttpClient.Builder().build()
            val ds = OkHttpDataSource.Factory(http).setDefaultRequestProperties(
                mapOf("Accept" to "*/*"))
            val exo = ExoPlayer.Builder(this)
                .setMediaSourceFactory(
                    androidx.media3.exoplayer.source.DefaultMediaSourceFactory(ds))
                .build()
            exo.setMediaItem(androidx.media3.common.MediaItem.fromUri(url))
            // Background lockscreen diputar terus (loop mulus) tanpa suara.
            exo.repeatMode = androidx.media3.common.Player.REPEAT_MODE_ALL
            exo.volume = 0f

            // TextureView (BUKAN SurfaceView/PlayerView): SurfaceView tidak
            // dirender di STB ini saat lockscreen memakai lock-task mode.
            var tex = bgTexture
            if (tex == null) {
                tex = android.view.TextureView(this).apply {
                    layoutParams = android.widget.FrameLayout.LayoutParams(
                        android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                        android.widget.FrameLayout.LayoutParams.MATCH_PARENT)
                    isOpaque = true
                }
                box.addView(tex, 0)
                bgTexture = tex
            }
            hidePanelPesan()
            tex.visibility = View.VISIBLE
            exo.setVideoTextureView(tex)

            exo.addListener(object : androidx.media3.common.Player.Listener {
                override fun onRenderedFirstFrame() {
                    Log.i(TAG, "Background lockscreen: frame pertama tampil")
                }

                override fun onPlayerError(
                    error: androidx.media3.common.PlaybackException
                ) {
                    Log.w(TAG, "Background video gagal: ${error.errorCodeName} ${error.message}")
                    runOnUiThread { showPanelPesan("Video tidak dapat dimuat") }
                }
            })
            exo.prepare()
            exo.playWhenReady = true
            bgPlayer = exo
            Log.i(TAG, "Background lockscreen: player dibuat untuk $url")
        } catch (e: Exception) {
            Log.w(TAG, "Gagal pasang background video: ${e.message}")
            showPanelPesan("Video tidak dapat dimuat")
        }
    }

    /** Teks-info di panel kanan, dipakai saat belum ada / gagal memuat video. */
    private fun showPanelPesan(pesan: String) {
        val box = findViewById<android.widget.FrameLayout>(R.id.fl_lock_video) ?: return
        val tv = findViewById<TextView>(R.id.tv_lock_video_info)
        if (tv != null) {
            tv.text = pesan
            tv.visibility = View.VISIBLE
        } else {
            // layout versi lama (tanpa tv_lock_video_info) — buat view sendiri
            val baru = TextView(this).apply {
                text = pesan
                setTextColor(0xFF7F9CB0.toInt())
                textSize = 15f
                gravity = android.view.Gravity.CENTER
            }
            box.addView(baru)
            tagPanelPesan = baru
        }
    }

    private fun hidePanelPesan() {
        val tv = findViewById<TextView>(R.id.tv_lock_video_info)
        tv?.visibility = View.GONE
        tagPanelPesan?.let {
            (it.parent as? android.view.ViewGroup)?.removeView(it)
            tagPanelPesan = null
        }
    }

    private var tagPanelPesan: View? = null

    private fun releaseBgPlayer() {
        val p = bgPlayer ?: return
        bgPlayer = null
        try {
            p.stop()
            p.release()
        } catch (e: Exception) {
            Log.w(TAG, "release bg player gagal: ${e.message}")
        }
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

    // Blokir SEMUA input dari remote (IR, Bluetooth, remote voice) selama
    // terkunci. Remote Bluetooth & voice sama-sama mengirim key event, jadi
    // menelan semua key event otomatis membungkam ketiganya — termasuk tombol
    // mic (KEYCODE_ASSIST) yang membuka asisten suara.
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (locked) return true
        return super.dispatchKeyEvent(event)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (locked) return true
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (locked) return true
        return super.onKeyUp(keyCode, event)
    }

    // Lock Task mode: menonaktifkan tombol HOME/recent/notifikasi/global
    // actions selama layar lock. Butuh device owner (lihat README).
    private fun enterLockTaskMode() {
        try { startLockTask() } catch (_: Exception) {}
    }

    private fun exitLockTaskMode() {
        try { stopLockTask() } catch (_: Exception) {}
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

        /**
         * Kasir mengunggah gambar bergerak baru → lockscreen yang sedang tampil
         * langsung memakai video baru (tanpa perlu menunggu lock berikutnya).
         * URL kosong = kembali ke background bawaan aplikasi.
         */
        fun updateBgUrl(url: String) {
            val act = instance ?: return
            act.runOnUiThread { act.applyLockBg(url) }
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
