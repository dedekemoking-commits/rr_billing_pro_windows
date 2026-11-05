package com.rrbillingpro.tvclient.media

import android.app.Activity
import com.rrbillingpro.tvclient.service.TvOverlayService
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import android.view.SurfaceView
import android.view.View
import android.view.WindowManager
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.TextView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import com.rrbillingpro.tvclient.R
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.net.Proxy
import java.util.concurrent.TimeUnit

/**
 * MediaActivity — pemutar video/gambar promosi fullscreen di client TV.
 *
 * Dipanggil dari TvOverlayService saat server kasir mengirim SHOW_MEDIA
 * ({type: video|image, url: http://<kasir>:8082/media/<file>}).
 * Ditutup via HIDE_MEDIA (finishInstance).
 *
 * Video memakai ExoPlayer (media3) — jauh lebih tahan banting daripada
 * VideoView/MediaPlayer bawaan di semua versi Android & merk box:
 *   - HTTP source: OkHttpDataSource (OkHttp 4.12) — lebih andal daripada
 *     HttpURLConnection bawaan yang sering HANG di Android 11 (layar hitam +
 *     spinner buffering tanpa henti, tanpa error).
 *   - decoder fallback ke software bila HW decoder STB hang (beberapa box
 *     Android 11 tidak mengeluarkan error, hanya buffering selamanya).
 *   - retry otomatis 3x (beberapa box gagal sekali lalu sukses)
 *   - watchdog buffering: bila >15 dtk stuck BUFFERING, tampilkan teks error
 *     (bukan spinner selamanya) + log logcat untuk diagnosa
 *   - kode error ditampilkan di layar (PlaybackException) untuk diagnosa
 *
 * Video otomatis LANJUT diputar saat TV/STB bangun dari sleep (SCREEN_ON):
 * posisi terakhir disimpan saat SCREEN_OFF, dipulihkan saat wake.
 *
 * Promo TIDAK diulang: video diputar 1x saja, gambar ditampilkan 5 detik.
 * Setelah selesai, pindah ke input/port terakhir TV (tv_last_used_input_id)
 * lewat Android TV Input Player (content://android.media.tv/passthrough/...).
 */
class MediaActivity : Activity() {

    private var surfaceView: SurfaceView? = null
    private var imageView: ImageView? = null
    private var progress: ProgressBar? = null
    private var errorText: TextView? = null

    private val mainHandler = Handler(Looper.getMainLooper())
    private var autoSwitchRunnable: Runnable? = null
    private var bufferingWatchdog: Runnable? = null

    private var player: ExoPlayer? = null
    private var videoUrl = ""
    private var streamUrl = ""
    private var localName = ""
    private var retryCount = 0
    private var preparedOnce = false

    // Waktu (elapsedRealtime) saat kasir/service meminta promo tampil — untuk
    // laporan "bangun -> frame pertama" (tv_promo_latency) ke kartu kasir.
    private var t0 = 0L
    private var latensiDilaporkan = false

    @Volatile
    private var videoReady = false

    @Volatile
    private var videoPosition = 0L

    private var screenReceiver: BroadcastReceiver? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        instance = this
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        // Promo diputar saat TV bangun dari tidur, jadi activity ini harus boleh
        // menyalakan layar sendiri. FLAG_TURN_SCREEN_ON hanya dihormati bila
        // activity yang membuat layarnya sendiri — makanya dulu dipakai power key
        // (input keyevent 26) sebagai jalan pintas, padahal perintah itu butuh
        // izin INJECT_EVENTS yang tidak dimiliki app ini (jadi diam-diam gagal
        // dan TV tetap di launcher).
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        }
        setContentView(R.layout.activity_media)

        surfaceView = findViewById(R.id.media_surface)
        imageView = findViewById(R.id.media_image)
        progress = findViewById(R.id.media_progress)
        errorText = findViewById(R.id.media_error)
        hideSystemUi()

        registerScreenReceiver()

        val type = intent.getStringExtra(EXTRA_TYPE) ?: "image"
        val url = intent.getStringExtra(EXTRA_URL) ?: ""
        localName = intent.getStringExtra(EXTRA_LOCAL) ?: ""
        t0 = intent.getLongExtra(EXTRA_T0, 0L)
        if (type == "video") {
            playVideo(url, localName)
        } else {
            loadImage(url, localName)
        }
    }

    /**
     * Aset lokal didahulukan (v4.13): semua video/gambar dikirim kasir lewat
     * adb push ke folder media dengan nama tetap. Kalau file lokal tidak ada
     * (mis. push gagal), baru pakai URL streaming sebagai cadangan.
     */
    private fun berkasLokal(nama: String, namaBawaan: String): File? {
        val kandidat = when {
            nama.isNotBlank() -> listOf(nama, namaBawaan)
            else -> listOf(namaBawaan)
        }
        for (n in kandidat) {
            try {
                val f = com.rrbillingpro.tvclient.util.Prefs.mediaFile(this, n)
                if (f.exists() && f.length() > 0) return f
            } catch (_: Exception) {
            }
        }
        return null
    }

    private fun laporkanLatensi() {
        if (latensiDilaporkan || t0 <= 0L) return
        latensiDilaporkan = true
        try {
            val ms = SystemClock.elapsedRealtime() - t0
            TvOverlayService.laporkanLatensiPromo(ms)
        } catch (_: Exception) {
        }
    }

    /** Resume video saat layar TV/STB bangun dari sleep. */
    private fun registerScreenReceiver() {
        try {
            val filter = IntentFilter().apply {
                addAction(Intent.ACTION_SCREEN_ON)
                addAction(Intent.ACTION_SCREEN_OFF)
            }
            screenReceiver = object : BroadcastReceiver() {
                override fun onReceive(context: Context, intent: Intent) {
                    when (intent.action) {
                        Intent.ACTION_SCREEN_OFF -> pauseVideoForSleep()
                        Intent.ACTION_SCREEN_ON -> resumeVideoFromSleep()
                    }
                }
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                registerReceiver(screenReceiver, filter, Context.RECEIVER_EXPORTED)
            } else {
                @Suppress("DEPRECATION")
                registerReceiver(screenReceiver, filter)
            }
        } catch (_: Exception) {
        }
    }

    private fun pauseVideoForSleep() {
        val p = player ?: return
        runOnUiThread {
            if (videoReady && p.isPlaying) {
                videoPosition = p.currentPosition
                p.pause()
            }
        }
    }

    private fun resumeVideoFromSleep() {
        val p = player ?: return
        runOnUiThread {
            if (!videoReady) return@runOnUiThread
            try {
                if (videoPosition > 0) p.seekTo(videoPosition)
            } catch (_: Exception) {
            }
            if (!p.isPlaying) p.play()
        }
    }

    private fun hideSystemUi() {
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
        window.decorView.setOnSystemUiVisibilityChangeListener { hideSystemUi() }
    }

    // Proxy.NO_PROXY: media promo datang dari server LAN kasir — JANGAN ikuti
    // proxy sistem TV (beberapa box Android 11 punya proxy aktif dari router/
    // ISP yang membuat unduhan media macet selamanya tanpa error).
    private val mediaHttpClient = OkHttpClient.Builder()
        .proxy(Proxy.NO_PROXY)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private fun playVideo(url: String, local: String = "") {
        val berkas = berkasLokal(local, LOCAL_PROMO_VIDEO)
        val sumberUri: Uri? = when {
            berkas != null -> {
                Log.i(TAG, "playVideo LOKAL: ${berkas.absolutePath}")
                Uri.fromFile(berkas)
            }
            url.isNotBlank() -> {
                Log.i(TAG, "playVideo STREAM: $url")
                Uri.parse(url)
            }
            else -> null
        }
        if (sumberUri == null) {
            // Tidak ada video lokal maupun URL — jangan tampilkan layar kosong
            // (inilah yang dulu terlihat seperti "app terbuka 1 detik"):
            // langsung tutup bersih tanpa menyentuh input TV.
            Log.w(TAG, "playVideo: tidak ada sumber video (lokal/URL kosong)")
            tutupBersih()
            return
        }
        releasePlayer()
        videoUrl = sumberUri.toString()
        streamUrl = url
        retryCount = 0
        preparedOnce = false
        videoReady = false
        videoPosition = 0
        imageView?.visibility = View.GONE
        errorText?.visibility = View.GONE
        progress?.visibility = View.VISIBLE

        // OkHttpDataSource: ganti HttpURLConnection yang rentan HANG di
        // Android 11 (spinner buffering selamanya tanpa error).
        // TAPI OkHttpDataSource TIDAK bisa membaca URI file:// (aset lokal
        // v4.13) — untuk file:// pakai sumber data default (file + http).
        val mediaSourceFactory = DefaultMediaSourceFactory(this)
        if (sumberUri.scheme != "file") {
            mediaSourceFactory.setDataSourceFactory(
                OkHttpDataSource.Factory(mediaHttpClient))
        }
        val exo = ExoPlayer.Builder(this)
            .setRenderersFactory(
                // Fallback ke software decoder bila HW decoder STB hang
                // (beberapa box Android 11 tidak error, hanya buffering).
                DefaultRenderersFactory(this)
                    .setEnableDecoderFallback(true))
            .setMediaSourceFactory(mediaSourceFactory)
            .build()
        player = exo
        exo.setVideoSurfaceView(surfaceView)
        exo.volume = 1f
        exo.addListener(object : Player.Listener {
            override fun onRenderedFirstFrame() {
                Log.i(TAG, "frame pertama tampil")
                laporkanLatensi()
            }

            override fun onPlaybackStateChanged(state: Int) {
                Log.i(TAG, "state=$state (url=$videoUrl)")
                when (state) {
                    Player.STATE_READY -> {
                        progress?.visibility = View.GONE
                        cancelBufferingWatchdog()
                        videoReady = true
                        if (!exo.isPlaying && !preparedOnce) exo.play()
                    }
                    Player.STATE_BUFFERING -> {
                        progress?.visibility = View.VISIBLE
                        armBufferingWatchdog()
                    }
                    Player.STATE_ENDED -> {
                        cancelBufferingWatchdog()
                        // Pindah input TIDAK boleh dipanggil di dalam callback
                        // player: activity masih resumed dan SurfaceView masih
                        // nempel, sehingga permintaan passthrough tenggelam di
                        // bawah task aplikasi sendiri dan yang naik ke depan
                        // adalah launcher Android (TV "kembali ke home").
                        // Keluar dulu lewat Handler, baru pindah.
                        jadwalPindahInput(SWITCH_DELAY_MS)
                    }
                    else -> {
                        cancelBufferingWatchdog()
                    }
                }
            }

            override fun onPlayerError(error: PlaybackException) {
                cancelBufferingWatchdog()
                progress?.visibility = View.GONE
                Log.e(TAG, "onPlayerError code=${error.errorCode} " +
                    "name=${error.errorCodeName} msg=${error.message}")
                if (retryCount < MAX_RETRIES) {
                    retryCount++
                    val delay = (1000L * retryCount)
                    Log.i(TAG, "retry $retryCount/$MAX_RETRIES after ${delay}ms")
                    mainHandler.postDelayed({ playVideo(streamUrl, localName) }, delay)
                } else {
                    videoReady = false
                    showError("Gagal memutar video.\n$videoUrl\n" +
                        "(error: ${error.errorCodeName} / ${error.errorCode})")
                }
            }
        })
        exo.setMediaItem(MediaItem.fromUri(sumberUri))
        exo.prepare()
    }

    /** Watchdog: kalau >15 dtk stuck BUFFERING, tampilkan error (bukan spinner selamanya). */
    private fun armBufferingWatchdog() {
        cancelBufferingWatchdog()
        bufferingWatchdog = Runnable {
            val p = player
            if (p != null && p.playbackState == Player.STATE_BUFFERING) {
                val buf = p.bufferedPosition
                val dur = p.duration
                Log.e(TAG, "watchdog: stuck BUFFERING > ${BUFFER_WATCHDOG_MS}ms url=$videoUrl " +
                    "buffered=$buf duration=$dur")
                progress?.visibility = View.GONE
                showError("Video macet (buffering > 15 dtk).\n$videoUrl\n" +
                    "Periksa server media & coba kirim ulang video.")
            }
        }
        mainHandler.postDelayed(bufferingWatchdog!!, BUFFER_WATCHDOG_MS)
    }

    private fun cancelBufferingWatchdog() {
        bufferingWatchdog?.let { mainHandler.removeCallbacks(it) }
        bufferingWatchdog = null
    }

    private fun releasePlayer() {
        player?.removeListener(emptyPlayerListener)
        player?.release()
        player = null
    }

    override fun onResume() {
        super.onResume()
        // Activity kembali ke depan (mis. STB bangun dari sleep) -> lanjut putar.
        resumeVideoFromSleep()
    }

    private fun loadImage(url: String, local: String = "") {
        surfaceView?.visibility = View.GONE
        progress?.visibility = View.VISIBLE
        val berkas = berkasLokal(local, LOCAL_PROMO_IMAGE)
        if (berkas == null && url.isBlank()) {
            // Tidak ada gambar lokal maupun URL — tutup bersih, jangan
            // menampilkan layar kosong/error ke pelanggan.
            Log.w(TAG, "loadImage: tidak ada sumber gambar (lokal/URL kosong)")
            tutupBersih()
            return
        }
        Thread {
            try {
                val bmp: Bitmap? = if (berkas != null) {
                    Log.i(TAG, "loadImage LOKAL: ${berkas.absolutePath}")
                    BitmapFactory.decodeFile(berkas.absolutePath)
                } else {
                    Log.i(TAG, "loadImage STREAM: $url")
                    // NO_PROXY: gambar promo dari server LAN kasir, jangan lewat proxy sistem.
                    val client = OkHttpClient.Builder().proxy(Proxy.NO_PROXY).build()
                    val req = Request.Builder().url(url).build()
                    var hasil: Bitmap? = null
                    client.newCall(req).execute().use { resp ->
                        if (!resp.isSuccessful) {
                            runOnUiThread { showError("HTTP ${resp.code} — $url") }
                            return@Thread
                        }
                        hasil = BitmapFactory.decodeStream(resp.body?.byteStream())
                    }
                    hasil
                }
                runOnUiThread {
                    progress?.visibility = View.GONE
                    if (bmp != null) {
                        // ImageView di-declare visibility="gone" di
                        // activity_media.xml — tanpa set VISIBLE di sini
                        // bitmap-nya tidak pernah tampil (layar hitam).
                        imageView?.visibility = View.VISIBLE
                        imageView?.setImageBitmap(bmp)
                        laporkanLatensi()
                        jadwalPindahInput()
                    } else {
                        val sumber = berkas?.absolutePath ?: url
                        showError("Gambar tidak valid.\n$sumber")
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { showError("Gagal memuat gambar.\n$url") }
            }
        }.start()
    }

    private fun showError(message: String) {
        progress?.visibility = View.GONE
        errorText?.text = message
        errorText?.visibility = View.VISIBLE
        jadwalPindahInput(IMAGE_SWITCH_MS)
    }

    /** Jadwalkan perpindahan ke input/port terakhir setelah promo selesai. */
    private fun jadwalPindahInput(delayMs: Long = IMAGE_SWITCH_MS) {
        autoSwitchRunnable?.let { mainHandler.removeCallbacks(it) }
        autoSwitchRunnable = Runnable { pindahKeInputTerakhir(0) }
        mainHandler.postDelayed(autoSwitchRunnable!!, delayMs)
    }

    /**
     * Kembalikan TV ke port HDMI terakhir setelah promo ditutup.
     *
     * Urutan WAJIB: tutup promo DULU, baru jalankan passthrough. Urutan lama
     * (startActivity passthrough lalu finish()) membuat passthrough yang baru
     * start langsung tenggelam di balik task aplikasi sendiri pada beberapa
     * firmware STB — hasil akhirnya TV kembali ke launcher Android, bukan ke
     * game. Karena itu start memakai applicationContext (aman dipanggil
     * setelah finish()) dan diberi jeda singkat.
     *
     * Server tidak bisa membuktikannya dari sisi app (tidak ada API publik
     * untuk membaca activity paling depan), jadi permintaan diulang bertahap
     * sebagai jaring pengaman: 3x per kandidat id input, dengan jeda
     * makin panjang. Semua percobaan dicatat di log & dilaporkan ke kasir.
     */
    private fun pindahKeInputTerakhir(percobaan: Int) {
        // ── Mode input pilihan kasir (v4.13) ────────────────────────────────
        // -1 "Jangan pakai": app TIDAK boleh menyentuh input sama sekali —
        //    TV memakai setelan inputnya sendiri. Ini juga mencegah app
        //    "merusak" setelan TV.
        //  0 "belum diisi": kembali ke port TERAKHIR yang dipakai sebelum
        //    TV tidur (dicatat service di Prefs saat SCREEN_OFF — id pasti,
        //    bukan tebakan). Tanpa catatan, promo ditutup apa adanya.
        val mode = com.rrbillingpro.tvclient.util.Prefs.hdmiPort(this)
        if (mode < 0) {
            // Mode "Jangan pakai": TV memakai setelan inputnya sendiri —
            // cukup tutup promo, JANGAN arahkan ke Home Android juga.
            Log.i(TAG, "mode input kasir=$mode — promo ditutup, input TIDAK disentuh")
            tutupBersih(keHomeAndroid = false)
            return
        }
        val kandidat: List<String>
        if (mode >= 1) {
            kandidat = kandidatInputId(mode)
        } else {
            val terakhir = com.rrbillingpro.tvclient.util.Prefs.getLastInput(this).trim()
            if (terakhir.isEmpty()) {
                Log.i(TAG, "mode input kasir=0 tanpa catatan port terakhir — " +
                        "promo ditutup, TV dikembalikan ke Home Android")
                tutupBersih()
                return
            }
            Log.i(TAG, "mode input kasir=0 — kembali ke port terakhir tercatat: $terakhir")
            kandidat = listOf(terakhir)
        }
        if (kandidat.isEmpty()) {
            // Tidak ada id input yang bisa dipastikan untuk port sasaran.
            // JANGAN menebak: membuka "HDMI pertama" hanya traumatized
            // pelanggan ke port kosong (layar hitam / no signal) — itu lebih
            // buruk daripada TV berhenti di Home Android yang kelihatan oleh
            // kasir. Wajib tutup bersih (dulu `return` telanjang = layar
            // promo nyangkut selamanya).
            Log.w(TAG, "pindah input DILEWATI: tidak ada id untuk port hdmi$mode — " +
                    "TV dikembalikan ke Home Android")
            TvOverlayService.laporkanPromoGagalPindahInput(kandidat)
            tutupBersih()
            return
        }
        val maksPercobaan = kandidat.size * VARIAN_PER_INPUT
        if (percobaan >= maksPercobaan) {
            Log.e(TAG, "pindah input GAGAL: $percobaan percobaan, id=$kandidat " +
                    "— TV dikembalikan ke Home Android")
            TvOverlayService.laporkanPromoGagalPindahInput(kandidat)
            // Sama seperti di atas: tanpa finish() di sini layar promo/frame
            // terakhir nyangkut permanen di sebagian firmware (freeze).
            tutupBersih()
            return
        }
        val inputId = kandidat[percobaan / VARIAN_PER_INPUT]
        val varian = (percobaan % VARIAN_PER_INPUT) + 1
        val intent = buildPassthroughIntent(inputId, varian)
        if (intent == null) {
            Log.w(TAG, "varian passthrough $varian tidak tersedia, id=$inputId")
        } else {
            val ctx = applicationContext
            try {
                // Tutup promo dulu: lepas surface player & keluar dari layar.
                releasePlayer()
                cancelBufferingWatchdog()
                if (!isFinishing) finish()
                ctx.startActivity(intent)
                Log.i(TAG, "pindah input coba=${percobaan + 1}/$maksPercobaan " +
                        "id=$inputId varian=$varian terkirim")
                jedaVerifikasi(inputId)
                return
            } catch (e: Exception) {
                Log.e(TAG, "pindah input coba=${percobaan + 1}/$maksPercobaan " +
                        "id=$inputId varian=$varian GAGAL ${e.javaClass.simpleName}: ${e.message}")
            }
        }
        // Ulangi ke varian berikutnya dengan jeda naik.
        val berikutnya = percobaan + 1
        if (berikutnya < maksPercobaan) {
            val jeda = JEDA_COBAL[percobaan.coerceAtMost(JEDA_COBAL.lastIndex)]
            mainHandler.postDelayed({ pindahKeInputTerakhir(berikutnya) }, jeda)
        }
    }

    /**
     * Verifikasi hasil passthrough.
     *
     * startActivity() tidak melempar exception BUKAN berarti TV benar-benar
     * pindah: intent bisa diterima STB lalu membuka port yang salah, dan
     * pelanggan melihat layar hitam. Jadi setelah jeda, baca ulang port yang
     * benar-benar dipakai lalu laporkan hasilnya ke kasir — kasir yang
     * memutuskan perlu/tidaknya mengirim ulang lewat ADB.
     */
    private fun jedaVerifikasi(inputId: String) {
        mainHandler.postDelayed({
            val sekarang = bacaPortDipakai()
            if (sekarang.isNullOrBlank()) {
                Log.w(TAG, "verifikasi gagal: port tidak terbaca (sasaran=$inputId)")
                TvOverlayService.laporkanPromoGagalPindahInput(listOf(inputId))
                return@postDelayed
            }
            if (bandingkanPort(sekarang, inputId)) {
                Log.i(TAG, "verifikasi OK: TV di $sekarang (sasaran=$inputId)")
                com.rrbillingpro.tvclient.util.Prefs.saveLastInput(this, inputId)
                TvOverlayService.laporkanPromoSelesai(inputId)
            } else {
                Log.w(TAG, "verifikasi GAGAL: TV di $sekarang, bukan $inputId")
                TvOverlayService.laporkanPromoSalahPort(inputId, sekarang)
            }
        }, VERIFIKASI_MS)
    }

    /** Port HDMI yang benar-benar sedang dipakai STB (null bila tak terbaca). */
    private fun bacaPortDipakai(): String? = try {
        android.provider.Settings.Secure.getString(contentResolver, "tv_last_used_input_id")
    } catch (_: Exception) {
        null
    }

    /**
     * Bandingkan dua id input. Bentuknya berbeda antar vendor
     * (com.mediatek.tis/.HdmiInputService/HW3 vs .../HDMI1), jadi yang
     * dibandingkan hanya penomoran port-nya.
     */
    private fun bandingkanPort(a: String, b: String): Boolean {
        val ka = portNormal(a)
        val kb = portNormal(b)
        return ka.isNotEmpty() && ka == kb
    }

    private fun portNormal(id: String): String {
        val angka = Regex("(\\d+)\\s*$").find(id.trim())?.groupValues?.get(1) ?: ""
        return if (angka.isEmpty()) id.trim().lowercase() else "hdmi$angka"
    }

    /**
     * Bangun intent passthrough. Dua varian:
     *
     * 1) lewat reflection `TunerService.getPassThroughIntent()` — platform
     *    yang menentukan sendiri MIME type yang cocok untuk firmware ini.
     *    API 23+, ada di semua Android TV (MediaTek, Realtek, Hisilicon,
     *    Amlogic, Rockchip, Allwinner, Qualcomm, Google TV). Jalur utama.
     *
     * 2) manual `setDataAndType(uri, "vnd.android.cursor.item/channel")`.
     *    Cadangan kalau reflection diblokir OEM.
     *
     * PENTING: harus `setDataAndType()`, BUKAN `type = ...`.
     * `Intent.setType()` di AOSP melakukan `mData = null` — Uri passthrough
     * ikut terhapus, intent tidak bisa dicocokkan, hasilnya
     * ActivityNotFoundException dan TV jatuh ke Home Android. Berlaku di
     * semua SoC karena itu perilaku framework, bukan vendor.
     *
     * Varian tanpa MIME type SENGAJA TIDAK dipakai: sudah diuji dan yang
     * terbuka adalah browser (com.tcl.browser PlayWebVideoActivity), bukan
     * passthrough — hanya mengembalikan pelanggan ke beranda internet.
     */
    private fun buildPassthroughIntent(inputId: String, varian: Int): Intent? {
        val ctx = applicationContext
        if (varian <= 1) {
            val dariTuner = passthroughLewatTunerService(ctx, inputId)
            if (dariTuner != null) {
                dariTuner.addFlags(FLAGS_PASSTHROUGH)
                Log.d(TAG, "intent passthrough dari TunerService (platform)")
                return dariTuner
            }
        }
        val uri = Uri.parse(
            "content://android.media.tv/passthrough/" + Uri.encode(inputId))
        return Intent().apply {
            action = Intent.ACTION_VIEW
            setDataAndType(uri, PASSTHROUGH_MIME)
            addFlags(FLAGS_PASSTHROUGH)
        }
    }

    private fun passthroughLewatTunerService(ctx: Context, inputId: String): Intent? {
        return try {
            val cls = Class.forName("android.media.tv.TunerService")
            val m = cls.getDeclaredMethod(
                "getPassThroughIntent", Context::class.java, String::class.java)
            m.isAccessible = true
            m.invoke(null, ctx, inputId) as? Intent
        } catch (e: Throwable) {
            Log.w(TAG, "TunerService.getPassThroughIntent tidak tersedia: ${e.javaClass.simpleName}")
            null
        }
    }

    /**
     * Kandidat id input untuk port sasaran.
     *
     * Prioritas (v4.13):
     *   1. `hdmi_input_hint` dari kasir — id firmware hasil kalibrasi otomatis
     *      per TV (inilah yang memperbaiki kasus "HDMI 1 -> TV di HDMI 3").
     *   2. Setting sistem `tv_last_used_input_id` HANYA bila nomor port-nya
     *      cocok dengan sasaran (tidak menebak port lain).
     *   3. Port yang sudah terbukti dipakai promo sebelumnya (Prefs) — juga
     *      hanya bila nomor port-nya cocok.
     *
     * HDMI "pertama yang terdaftar" SENGAJA TIDAK dipakai sebagai tebakan.
     * Dulu ada di daftar ini dan itulah penyebab layar hitam: setelah TV
     * bangun dari tidur banyak firmware me-reset `tv_last_used_input_id`
     * jadi kosong, lalu app asal membuka HDMI1 — padahal game ada di HDMI3.
     */
    private fun kandidatInputId(mode: Int): List<String> {
        val sasaran = "hdmi$mode"
        val hint = com.rrbillingpro.tvclient.util.Prefs.hdmiInputHint(this).trim()
        if (hint.isNotEmpty()) {
            // Hint = id otoritatif (hasil verifikasi kasir). Satu kandidat,
            // tanpa tebakan tambahan.
            Log.i(TAG, "kandidat dari hint kasir: $hint (sasaran hdmi$mode)")
            return listOf(hint)
        }
        val hasil = LinkedHashSet<String>()
        try {
            Settings.Secure.getString(contentResolver, "tv_last_used_input_id")
                ?.trim()?.takeIf { it.isNotEmpty() }
                ?.takeIf { portNormal(it) == sasaran }
                ?.let { hasil.add(it) }
        } catch (_: Exception) {
        }
        val tersimpan = com.rrbillingpro.tvclient.util.Prefs.getLastInput(this).trim()
        if (tersimpan.isNotEmpty() && portNormal(tersimpan) == sasaran) hasil.add(tersimpan)
        return hasil.toList()
    }

    /**
     * Tutup activity TANPA menyentuh input TV. Wajib dipanggil di semua jalur
     * yang tidak bisa menjamin perpindahan input: inti perbaikan freeze
     * "frame terakhir promo nyangkut" di sebagian firmware.
     *
     * v4.15: karena RRBilling terdaftar sebagai Home default, finish() saja
     * membuat TV mendarat di lockscreen RRBilling (app "terbuka kembali").
     * Kecuali mode input -1 ("Jangan pakai"), activity ditutup lalu TV
     * diarahkan ke launcher/Home Android asli.
     */
    private fun tutupBersih(keHomeAndroid: Boolean = true) {
        autoSwitchRunnable?.let { mainHandler.removeCallbacks(it) }
        autoSwitchRunnable = null
        releasePlayer()
        cancelBufferingWatchdog()
        if (!isFinishing) finish()
        if (keHomeAndroid) kembaliKeHomeAndroid()
    }

    /**
     * Arahkan TV ke launcher bawaan (Home Android), bukan lockscreen
     * RRBilling. Dilewati saat TV terkunci supaya kunci tidak tertembus.
     */
    private fun kembaliKeHomeAndroid() {
        val svc = com.rrbillingpro.tvclient.service.TvOverlayService.instance
        val terkunci = svc?.isLocked ?: com.rrbillingpro.tvclient.util.Prefs.isLocked(this)
        if (terkunci) {
            Log.i(TAG, "Home Android dilewati: TV terkunci")
            return
        }
        val ok = com.rrbillingpro.tvclient.util.HomeAndroid.bukaHomeAndroid(applicationContext)
        TvOverlayService.laporkanPromoKeHome(ok)
        Log.i(TAG, "kembali ke Home Android ok=$ok")
    }

    /**
     * Kasir mengirim promo baru saat yang lama masih tampil (tombol "putar
     * lagi"): mulai dari awal di activity yang sama supaya tidak ada dua promo
     * menumpuk dan tidak perlu keluar-masuk layar.
     */
    fun putarUlang(type: String, url: String, local: String = "") {
        Log.i(TAG, "putar ulang promo type=$type url=$url local=$local")
        cancelBufferingWatchdog()
        mainHandler.postDelayed({
            when (type) {
                "video" -> playVideo(url, local)
                else -> loadImage(url, local)
            }
        }, 200)
    }

    /**
     * Dipakai kasir (HIDE_MEDIA) & service: tutup promo yang sedang tampil lalu
     * kembali ke port HDMI. `finishInstance()` telanjang justru mendarat di
     * launcher Android karena tidak ada yang mengarahkan ke input HDMI lagi.
     */
    fun tutupDanKembaliKeInput() {
        Log.i(TAG, "tutup promo dari kasir -> kembali ke input HDMI")
        releasePlayer()
        cancelBufferingWatchdog()
        jadwalPindahInput(SWITCH_DELAY_MS)
    }

    override fun onDestroy() {
        try {
            autoSwitchRunnable?.let { mainHandler.removeCallbacks(it) }
            autoSwitchRunnable = null
        } catch (_: Exception) {
        }
        try {
            if (screenReceiver != null) {
                unregisterReceiver(screenReceiver)
                screenReceiver = null
            }
        } catch (_: Exception) {
        }
        if (instance === this) instance = null
        releasePlayer()
        // Kabari kasir: layar kembali ke input/port terakhir (bukan promo lagi).
        TvOverlayService.onPromoSelesai()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_TYPE = "type"
        const val EXTRA_URL = "url"
        const val EXTRA_LOCAL = "local"
        const val EXTRA_T0 = "t0"
        private const val MAX_RETRIES = 3
        private const val BUFFER_WATCHDOG_MS = 15_000L
        private const val TAG = "RRMedia"

        // Nama tetap aset lokal (adb push dari kasir, semua TV seragam).
        const val LOCAL_PROMO_VIDEO = "promo.mp4"
        const val LOCAL_PROMO_IMAGE = "promo.jpg"

        // Jeda promo -> input: cukup untuk activity promo keluar dari layar.
        private const val SWITCH_DELAY_MS = 350L
        // Gambar/error tidak perlu buru-buru: tampilkan 5 detik biar terbaca.
        private const val IMAGE_SWITCH_MS = 5000L
        // Berapa banyak varian intent per kandidat id input.
        private const val VARIAN_PER_INPUT = 2
        private val JEDA_COBAL = longArrayOf(600L, 1500L, 3000L)
        // Jeda sebelum membaca ulang port untuk verifikasi hasil passthrough.
        private const val VERIFIKASI_MS = 4000L
        private const val PASSTHROUGH_MIME = "vnd.android.cursor.item/channel"
        private const val FLAGS_PASSTHROUGH = Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_REORDER_TO_FRONT

        @Volatile
        var instance: MediaActivity? = null
            private set

        private val emptyPlayerListener = object : Player.Listener {}

        fun start(context: Context, type: String, url: String, local: String = "") {
            finishInstance()
            val intent = Intent(context, MediaActivity::class.java)
                .putExtra(EXTRA_TYPE, type)
                .putExtra(EXTRA_URL, url)
                .putExtra(EXTRA_LOCAL, local)
                // Waktu mulai (elapsedRealtime) — MediaActivity menghitung
                // selisih ke frame pertama lalu melapor ke kasir
                // (CLIENT_EVENT tv_promo_latency) untuk mengukur anti-flash.
                .putExtra(EXTRA_T0, android.os.SystemClock.elapsedRealtime())
                // NO_ANIMATION: jangan tampilkan animasi transisi activity —
                // animasi itu bagian dari "kedipan" saat promo dibuka.
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_NO_ANIMATION)
            context.startActivity(intent)
        }

        fun finishInstance() {
            instance?.finish()
        }

        /**
         * Tutup promo yang sedang tampil lalu kembali ke port HDMI — dipakai
         * kasir (HIDE_MEDIA). Promo yang tidak tampil: biarkan, karena STB
         * memang sedang di input/launcher atas pilihan kasir.
         */
        fun tutupDanKembaliKeInput() {
            instance?.tutupDanKembaliKeInput()
        }
    }
}

