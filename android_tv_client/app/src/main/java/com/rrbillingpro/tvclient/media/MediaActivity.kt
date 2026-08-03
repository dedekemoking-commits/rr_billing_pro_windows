package com.rrbillingpro.tvclient.media

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.BitmapFactory
import android.media.tv.TvInputInfo
import android.media.tv.TvInputManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.SurfaceView
import android.view.View
import android.view.WindowManager
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.TextView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import com.rrbillingpro.tvclient.R
import okhttp3.OkHttpClient
import okhttp3.Request

/**
 * MediaActivity — pemutar video/gambar promosi fullscreen di client TV.
 *
 * Dipanggil dari TvOverlayService saat server kasir mengirim SHOW_MEDIA
 * ({type: video|image, url: http://<kasir>:8082/media/<file>}).
 * Ditutup via HIDE_MEDIA (finishInstance).
 *
 * Video memakai ExoPlayer (media3) — jauh lebih tahan banting daripada
 * VideoView/MediaPlayer bawaan di semua versi Android & merk box:
 *   - HTTP source toleran ke server kasir (HEAD/Range/206/keep-alive)
 *   - retry otomatis 3x (beberapa box gagal sekali lalu sukses)
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

    private var player: ExoPlayer? = null
    private var videoUrl = ""
    private var retryCount = 0
    private var preparedOnce = false

    @Volatile
    private var videoReady = false

    @Volatile
    private var videoPosition = 0L

    private var screenReceiver: BroadcastReceiver? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        instance = this
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_media)

        surfaceView = findViewById(R.id.media_surface)
        imageView = findViewById(R.id.media_image)
        progress = findViewById(R.id.media_progress)
        errorText = findViewById(R.id.media_error)
        hideSystemUi()

        registerScreenReceiver()

        val type = intent.getStringExtra(EXTRA_TYPE) ?: "image"
        val url = intent.getStringExtra(EXTRA_URL) ?: ""
        if (type == "video") {
            playVideo(url)
        } else {
            loadImage(url)
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

    private fun playVideo(url: String) {
        releasePlayer()
        videoUrl = url
        retryCount = 0
        preparedOnce = false
        videoReady = false
        videoPosition = 0
        imageView?.visibility = View.GONE
        errorText?.visibility = View.GONE
        progress?.visibility = View.VISIBLE

        val exo = ExoPlayer.Builder(this)
            .setMediaSourceFactory(
                DefaultMediaSourceFactory(this)
                    .setDataSourceFactory(
                        DefaultHttpDataSource.Factory()
                            .setAllowCrossProtocolRedirects(true)))
            .build()
        player = exo
        exo.setVideoSurfaceView(surfaceView)
        exo.volume = 1f
        exo.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                when (state) {
                    Player.STATE_READY -> {
                        progress?.visibility = View.GONE
                        videoReady = true
                        if (!exo.isPlaying && !preparedOnce) exo.play()
                    }
                    Player.STATE_BUFFERING -> progress?.visibility = View.VISIBLE
                    Player.STATE_ENDED -> switchToLastInput()
                    else -> Unit
                }
            }

            override fun onPlayerError(error: PlaybackException) {
                progress?.visibility = View.GONE
                if (retryCount < MAX_RETRIES) {
                    retryCount++
                    val delay = (1000L * retryCount)
                    mainHandler.postDelayed({ playVideo(videoUrl) }, delay)
                } else {
                    videoReady = false
                    showError("Gagal memutar video.\n$url\n" +
                        "(error: ${error.errorCodeName} / ${error.errorCode})")
                }
            }
        })
        exo.setMediaItem(MediaItem.fromUri(Uri.parse(url)))
        exo.prepare()
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

    private fun loadImage(url: String) {
        surfaceView?.visibility = View.GONE
        progress?.visibility = View.VISIBLE
        Thread {
            try {
                val client = OkHttpClient()
                val req = Request.Builder().url(url).build()
                client.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        runOnUiThread { showError("HTTP ${resp.code} — $url") }
                        return@Thread
                    }
                    val bmp = BitmapFactory.decodeStream(resp.body?.byteStream())
                    runOnUiThread {
                        progress?.visibility = View.GONE
                        if (bmp != null) {
                            imageView?.setImageBitmap(bmp)
                            scheduleAutoSwitch()
                        } else {
                            showError("Gambar tidak valid.\n$url")
                        }
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
        scheduleAutoSwitch()
    }

    /** Pindah ke input/port terakhir TV setelah promo selesai (video 1x / gambar 5 dtk). */
    private fun scheduleAutoSwitch() {
        autoSwitchRunnable?.let { mainHandler.removeCallbacks(it) }
        autoSwitchRunnable = Runnable { switchToLastInput() }
        mainHandler.postDelayed(autoSwitchRunnable!!, 5000)
    }

    private fun switchToLastInput() {
        val inputId = lastTvInputId()
        if (inputId.isNotEmpty()) {
            try {
                val uri = Uri.parse("content://android.media.tv/passthrough/" + Uri.encode(inputId))
                val intent = Intent(Intent.ACTION_VIEW, uri)
                intent.type = "vnd.android.cursor.item/channel"
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                startActivity(intent)
            } catch (_: Exception) {
            }
        }
        finish()
    }

    /** Input terakhir yang dipakai TV; fallback ke input HDMI pertama. */
    private fun lastTvInputId(): String {
        try {
            Settings.Secure.getString(contentResolver, "tv_last_used_input_id")
                ?.takeIf { it.isNotBlank() }?.let { return it }
        } catch (_: Exception) {
        }
        try {
            val mgr = getSystemService(Context.TV_INPUT_SERVICE) as? TvInputManager ?: return ""
            return mgr.tvInputList.firstOrNull { it.type == TvInputInfo.TYPE_HDMI }?.id.orEmpty()
        } catch (_: Exception) {
        }
        return ""
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
        super.onDestroy()
    }

    companion object {
        const val EXTRA_TYPE = "type"
        const val EXTRA_URL = "url"
        private const val MAX_RETRIES = 3

        @Volatile
        var instance: MediaActivity? = null
            private set

        private val emptyPlayerListener = object : Player.Listener {}

        fun start(context: Context, type: String, url: String) {
            finishInstance()
            val intent = Intent(context, MediaActivity::class.java)
                .putExtra(EXTRA_TYPE, type)
                .putExtra(EXTRA_URL, url)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
        }

        fun finishInstance() {
            instance?.finish()
        }
    }
}
