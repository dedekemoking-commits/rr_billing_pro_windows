package com.rrbillingpro.tvclient.overlay

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import com.rrbillingpro.tvclient.permission.OverlayPermission
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.Proxy
import java.util.concurrent.TimeUnit

/**
 * QrOverlay — layar QR sesi member di TV.
 *
 * Ditampilkan saat kasir menekan tombol 👤 MEMBER pada kartu TV (server kasir
 * mengirim action SHOW_QR). Pelanggan memindai QR pakai HP-nya, lalu memasukkan
 * nama member + PIN di halaman web; kalau benar, sesi member berjalan
 * otomatis dan server mengirim HIDE_QR.
 *
 * Tata letak (sesuai permintaan kasir):
 *   - KIRI ±25%  : gambar QR + teks "Scan untuk mulai"
 *   - KANAN ±75% : video MP4 loop (gambar bergerak tempat rental, diunggah kasir
 *                  lewat Overlay → Upload Gambar Bergerak) + info rental/grup TV.
 *
 * Berbeda MediaActivity: overlay ini TIDAK menutup sendiri — hilang hanya saat
 * HIDE_QR (sesi mulai / kasir batal / kedaluwarsa).
 */
class QrOverlay(private val context: Context) {

    companion object {
        /**
         * Jeda sebelum video diulang setelah satu putaran selesai (ms).
         * 0 = LANGSUNG mengulang dari frame pertama, tanpa jeda hitam di
         * antaranya. Pakai REPEAT_MODE_ONE sebagai mekanisme utama (putaran
         * penuh -> ulang, mulus); handler STATE_ENDED di bawah hanya
         *Cadangan bila perangkat mengabaikan repeat mode.
         */
        const val VIDEO_RESTART_DELAY_MS = 0L
    }

    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val mainHandler = Handler(Looper.getMainLooper())

    private var root: View? = null
    private var player: ExoPlayer? = null
    private var qrView: ImageView? = null
    private var teksMeja: TextView? = null
    private var videoBox: FrameLayout? = null
    private var promoView: ImageView? = null

    val isShowing: Boolean get() = root != null

    fun show(qrUrl: String, mejaId: String = "", grup: String = "",
             rental: String = "", bgUrl: String = "") {
        if (root != null) hide()
        tryShow(qrUrl, mejaId, grup, rental, bgUrl, attempt = 0)
    }

    @Suppress("UNUSED_PARAMETER")
    private fun tryShow(qrUrl: String, mejaId: String, grup: String,
                        rental: String, bgUrl: String, attempt: Int) {
        if (root != null) return

        val container = FrameLayout(context).apply {
            // Latar benar-benar hitam pekat (0xFF000000): kolom kanan dibuat
            // transparan penuh agar tidak menerawang launcher/ikon di bawahnya.
            setBackgroundColor(0xFF000000.toInt())
        }

        val row = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        }
        container.addView(row)

        // ── KIRI: panel QR (¼ layar) ──
        val kiri = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            // Latar terang hanya di kolom QR supaya kode mudah dipindai kamera HP.
            setBackgroundColor(0xFFFFFFFF.toInt())
            setPadding(dp(18), dp(18), dp(18), dp(18))
            layoutParams = LinearLayout.LayoutParams(0,
                FrameLayout.LayoutParams.MATCH_PARENT, 1f)
        }
        qrView = ImageView(context).apply {
            // PNG QR sudah berlatar putih — biarkan pas (centerInside).
            setBackgroundColor(Color.WHITE)
            scaleType = ImageView.ScaleType.CENTER_INSIDE
            layoutParams = LinearLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        kiri.addView(qrView)
        kiri.addView(TextView(context).apply {
            text = "📷  SCAN QR INI"
            setTextColor(0xFF00506B.toInt())
            textSize = 22f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, 0)
        })
        kiri.addView(TextView(context).apply {
            text = "Masukkan nama & PIN member"
            setTextColor(0xFF12455C.toInt())
            textSize = 14f
            gravity = Gravity.CENTER
        })
        row.addView(kiri)

        // ── KANAN: video gambar bergerak + info rental (¾ layar) ──
        val kanan = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            // Hitam penuh: teks info tidak boleh bercampur dengan ikon TV.
            setBackgroundColor(0xFF000000.toInt())
            setPadding(dp(16), dp(12), dp(16), dp(12))
            layoutParams = LinearLayout.LayoutParams(0,
                FrameLayout.LayoutParams.MATCH_PARENT, 3f)
        }
        val videoBox = FrameLayout(context).apply {
            layoutParams = LinearLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        val promo = ImageView(context).apply {
            setImageDrawable(ColorDrawable(0xFF0A1420.toInt()))
            scaleType = ImageView.ScaleType.CENTER_CROP
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT)
        }
        videoBox.addView(promo)
        kanan.addView(videoBox)

        teksMeja = TextView(context).apply {
            text = memberHeadline(mejaId, grup, rental)
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 26f
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, dp(4))
        }
        kanan.addView(teksMeja)
        kanan.addView(TextView(context).apply {
            text = "Sesi member · masukkan nama & PIN di HP untuk mulai"
            setTextColor(0xFF9FB6C8.toInt())
            textSize = 15f
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, dp(12))
        })
        row.addView(kanan)

        this.videoBox = videoBox
        this.promoView = promo

        val type = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }
        val flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            type,
            flags,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.CENTER
        }

        try {
            wm.addView(container, params)
            root = container
            Log.i("QrOverlay", "QR overlay tampil (meja=$mejaId grup=$grup)")
            if (qrUrl.isNotBlank()) loadQrImage(qrView, qrUrl)
            if (bgUrl.isNotBlank()) startLoopVideo(videoBox, bgUrl, promo)
        } catch (e: Exception) {
            root = null
            if (attempt >= 2) {
                Log.w("QrOverlay", "Gagal tampil setelah 3x: ${e.message} — cek izin overlay")
            } else {
                Log.w("QrOverlay", "Gagal tampil (${e.message}) — retry ${attempt + 2}/3")
                mainHandler.postDelayed({
                    tryShow(qrUrl, mejaId, grup, rental, bgUrl, attempt + 1)
                }, 1500L)
            }
        }
    }

    private fun memberHeadline(mejaId: String, grup: String, rental: String): String {
        val parts = mutableListOf<String>()
        if (rental.isNotBlank()) parts += rental
        if (mejaId.isNotBlank()) parts += mejaId
        if (grup.isNotBlank()) parts += "Grup $grup"
        return if (parts.isEmpty()) "Sesi Member" else parts.joinToString(" · ")
    }

    /** Muat PNG QR dari media server kasir (NO_PROXY — LAN, bukan internet). */
    private fun loadQrImage(view: ImageView?, url: String) {
        if (view == null) return
        Thread {
            try {
                val client = OkHttpClient.Builder().proxy(Proxy.NO_PROXY).build()
                val req = Request.Builder().url(url).build()
                client.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        Log.w("QrOverlay", "QR HTTP ${resp.code}")
                        return@use
                    }
                    val bytes = resp.body?.bytes() ?: return@use
                    val bmp = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    if (bmp != null) {
                        mainHandler.post { view.setImageBitmap(bmp) }
                    } else {
                        Log.w("QrOverlay", "Bitmap QR gagal decode")
                    }
                }
            } catch (e: Exception) {
                Log.w("QrOverlay", "Gagal memuat QR: ${e.message}")
            }
        }.start()
    }

    /** Putar MP4 loop (gambar bergerak) di panel kanan. */
    private fun startLoopVideo(box: FrameLayout, url: String, target: ImageView) {
        try {
            val http = OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(10, TimeUnit.SECONDS)
                .build()
            val ds = OkHttpDataSource.Factory(http).setDefaultRequestProperties(
                mapOf("Accept" to "*/*"))
            val exo = ExoPlayer.Builder(box.context)
                .setMediaSourceFactory(
                    androidx.media3.exoplayer.source.DefaultMediaSourceFactory(ds))
                .build()
            exo.setMediaItem(MediaItem.fromUri(url))
            // Satu putaran penuh → langsung diulang dari frame pertama, tanpa jeda.
            // REPEAT_MODE_ONE (bukan REPEAT_MODE_ALL) = ulangi video ini saja;
            // jeda antar putaran dibuat 0 (lihat VIDEO_RESTART_DELAY_MS).
            exo.repeatMode = Player.REPEAT_MODE_ONE
            exo.volume = 0f            // tanpa suara — TV harus tetap senyap

            // PENTUNG: pakai TextureView, BUKAN SurfaceView/PlayerView.
            // SurfaceView tidak bisa dirender di dalam overlay window
            // (TYPE_APPLICATION_OVERLAY) -> video jadi hitam / tidak terlihat,
            // dan layar di bawahnya ikut menerawang.
            val tv = android.view.TextureView(box.context).apply {
                layoutParams = FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.MATCH_PARENT)
                isOpaque = true
            }
            box.addView(tv)
            exo.setVideoTextureView(tv)

            exo.addListener(object : Player.Listener {
                override fun onRenderedFirstFrame() {
                    // Sembunyikan gambar fallback hanya setelah frame pertama
                    // benar-benar tampil.
                    mainHandler.post { target.visibility = View.GONE }
                }

                override fun onPlaybackStateChanged(state: Int) {
                    if (state == Player.STATE_ENDED) {
                        // Satu putaran selesai -> jeda sebentar, lalu putar lagi
                        // dari awal (bukan menyambung potongan akhir ke awal).
                        Log.i("QrOverlay", "Video bg selesai satu putaran → diulang")
                        mainHandler.postDelayed({
                            try {
                                exo.seekTo(0)
                                exo.playWhenReady = true
                            } catch (e: Exception) {
                                Log.w("QrOverlay", "ulang video gagal: ${e.message}")
                            }
                        }, VIDEO_RESTART_DELAY_MS)
                    }
                }

                override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
                    Log.w("QrOverlay", "Video bg gagal: ${error.errorCodeName}")
                    mainHandler.post {
                        tv.visibility = View.GONE
                        target.visibility = View.VISIBLE
                    }
                }
            })
            exo.prepare()
            exo.playWhenReady = true
            player = exo
        } catch (e: Exception) {
            Log.w("QrOverlay", "Gagal mulai video bg: ${e.message}")
        }
    }

    /** Update teks info (mis. nama rental berubah). */
    fun updateRental(rental: String, grup: String = "") {
        mainHandler.post {
            teksMeja?.text = memberHeadline("", grup, rental)
        }
    }

    /** Ganti video panel kanan tanpa menutup overlay (kasir upload baru). */
    fun updateBgVideo(url: String) {
        val box = videoBox ?: return
        val target = promoView ?: return
        if (url.isBlank()) return
        mainHandler.post {
            try {
                stopVideo()
                startLoopVideo(box, url, target)
            } catch (e: Exception) {
                Log.w("QrOverlay", "updateBgVideo gagal: ${e.message}")
            }
        }
    }

    fun hide() {
        stopVideo()
        val view = root ?: return
        root = null
        qrView = null
        teksMeja = null
        videoBox = null
        promoView = null
        mainHandler.post {
            try {
                wm.removeView(view)
                Log.i("QrOverlay", "QR overlay disembunyikan")
            } catch (e: Exception) {
                Log.w("QrOverlay", "removeView gagal: ${e.message}")
            }
        }
    }

    private fun stopVideo() {
        val exo = player ?: return
        player = null
        mainHandler.post {
            try {
                exo.stop()
                exo.release()
            } catch (e: Exception) {
                Log.w("QrOverlay", "release player gagal: ${e.message}")
            }
        }
    }

    private fun dp(v: Int): Int = (v * context.resources.displayMetrics.density).toInt()
}
