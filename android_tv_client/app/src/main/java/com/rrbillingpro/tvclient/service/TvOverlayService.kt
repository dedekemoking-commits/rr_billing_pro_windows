package com.rrbillingpro.tvclient.service

import android.app.ActivityManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import com.rrbillingpro.tvclient.MainActivity
import com.rrbillingpro.tvclient.R
import com.rrbillingpro.tvclient.lockscreen.LockScreenActivity
import com.rrbillingpro.tvclient.media.MediaActivity
import com.rrbillingpro.tvclient.model.Actions
import com.rrbillingpro.tvclient.model.LockDetail
import com.rrbillingpro.tvclient.model.ServerMessage
import com.rrbillingpro.tvclient.net.TimerEngine
import com.rrbillingpro.tvclient.net.WebSocketManager
import com.rrbillingpro.tvclient.overlay.OverlayWidget
import com.rrbillingpro.tvclient.overlay.PinOverlay
import com.rrbillingpro.tvclient.permission.OverlayPermission
import com.rrbillingpro.tvclient.util.Prefs
import org.json.JSONObject

/**
 * Foreground Service — inti aplikasi:
 *  1. Menjaga koneksi WebSocket tetap hidup walau game/aplikasi lain terbuka.
 *  2. Menjalankan TimerEngine countdown sisa waktu.
 *  3. Menampilkan/menyembunyikan Floating Overlay Widget.
 *  4. Membuka/menutup LockScreenActivity saat LOCK_SCREEN / UNLOCK_SCREEN.
 */
class TvOverlayService : Service() {

    private val mainHandler = Handler(Looper.getMainLooper())

    private var ws: WebSocketManager? = null
    private var overlay: OverlayWidget? = null
    private var pinOverlay: PinOverlay? = null
    private var timer: TimerEngine? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    // Health-check overlay (interval 30 dtk): jika sesi berjalan tapi overlay
    // tidak tampil (mis. addView ditolak sekali / di-hide oleh ROM ketat seperti
    // TCL), langsung re-show dari state terakhir — tidak menunggu pesan server.
    private var healthCheck: Runnable? = null

    @Volatile
    private var locked = false

    @Volatile
    private var lockDetail: LockDetail? = null

    @Volatile
    private var lastTotal: String = "Rp 0"

    @Volatile
    private var lastLunas: String = ""

    @Volatile
    private var lastTagihan: String = ""

    @Volatile
    private var lastMeja: String = "MEJA"

    @Volatile
    private var lastRental: String = "RR Billing Pro"

    @Volatile
    private var overlayMode: String = "always"

    @Volatile
    private var overlayLastMinutes: Int = 5

    // Video promosi yang dikirim kasir bersama LOCK_SCREEN — diputar 1x saat
    // TV bangun dari tidur, lalu pindah ke port/input terakhir yang dipakai.
    @Volatile
    private var lastPromoUrl: String = ""
    private var lastPromoType: String = "video"

    // Cold boot: layar sudah nyala saat service mulai (ACTION_SCREEN_ON sudah
    // lewat sebelum proses lahir) — promo tetap diputar 1x setelah boot.
    private var coldBootPromoDone = false

    // Kunci promo "1x per bangun": true saat SCREEN_OFF, false setelah promo
    // diputar (atau dikonsumsi cold boot) — SCREEN_ON ganda/nyasar pasca-boot
    // tidak menyebabkan dobel putar.
    private var wakePromoArmed = true

    private var screenReceiver: BroadcastReceiver? = null

    private val listeners = mutableListOf<StateListener>()

    interface StateListener {
        fun onLockChanged(locked: Boolean)
        fun onStatusChanged(connected: Boolean)
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        lastMeja = Prefs.mejaId(this).ifBlank { "MEJA" }
        // Restore promo terakhir agar tetap diputar 1x setelah TV reboot total
        // (mati listrik / cold boot) — URL terakhir tersimpan di Prefs.
        lastPromoUrl = Prefs.promoUrl(this)
        lastPromoType = Prefs.promoType(this)
        startInForeground()
        registerScreenReceiver()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startInForeground()
        ensureRunning()
        maybePlayPromoOnColdBoot()
        return START_STICKY
    }

    // Saat app di-swipe dari recents / ditutup: mulai ulang service agar
    // overlay timer & WebSocket tidak ikut mati (overlay tetap tampil).
    override fun onTaskRemoved(rootIntent: Intent?) {
        try {
            val restart = Intent(applicationContext, TvOverlayService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                applicationContext.startForegroundService(restart)
            } else {
                @Suppress("DEPRECATION")
                applicationContext.startService(restart)
            }
        } catch (_: Exception) {
        }
        super.onTaskRemoved(rootIntent)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        unregisterScreenReceiver()
        releaseKeepAlive()
        stopTimerAndWs()
        overlay?.hide()
        pinOverlay?.hide()
        super.onDestroy()
        if (instance === this) instance = null
    }

    // ── Bangun dari tidur: putar video promosi 1x lalu port terakhir ─────────
    private fun registerScreenReceiver() {
        try {
            val filter = IntentFilter().apply {
                addAction(Intent.ACTION_SCREEN_ON)
                addAction(Intent.ACTION_SCREEN_OFF)
            }
            screenReceiver = object : BroadcastReceiver() {
                override fun onReceive(context: Context, intent: Intent) {
                    when (intent.action) {
                        Intent.ACTION_SCREEN_ON -> {
                            sendScreenState(true)
                            onScreenWake()
                        }
                        Intent.ACTION_SCREEN_OFF -> {
                            wakePromoArmed = true
                            sendScreenState(false)
                        }
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

    private fun unregisterScreenReceiver() {
        try {
            if (screenReceiver != null) {
                unregisterReceiver(screenReceiver)
                screenReceiver = null
            }
        } catch (_: Exception) {
        }
    }

    /** SCREEN_ON: promo 1x -> input terakhir. Jalan walau app sudah di-unlock
     * (server kirim UNLOCK_SCREEN saat kasir konfirmasi waktu habis) — selama
     * lastPromoUrl masih terisi. Lockscreen "WAKTU SEWA HABIS" tidak muncul
     * lagi di alur bangun-tidur.
     *
     * R3: media terakhir (video ATAU gambar) diputar setiap TV bangun dari
     * tidur, sampai media baru dikirim (SHOW_MEDIA/LOCK_SCREEN mengganti arm).
     * Server TIDAK lagi mengirim ulang SHOW_MEDIA saat reconnect WS — jadi
     * tidak ada dobel putar dan tidak ada putar ulang saat blip/restart. */
    private fun onScreenWake() {
        if (!wakePromoArmed) return
        wakePromoArmed = false
        if (lastPromoUrl.isBlank()) return
        mainHandler.post {
            // MediaActivity memutar media sekali lalu otomatis switch ke
            // port/input terakhir yang dipakai (tv_last_used_input_id).
            MediaActivity.start(this, lastPromoType, lastPromoUrl)
        }
    }

    /** Cold boot / service mulai dengan layar sudah menyala: ACTION_SCREEN_ON
     * tidak pernah diterima (event terjadi sebelum proses lahir), jadi promo
     * terakhir (tersimpan di Prefs) diputar 1x di sini. Hanya sekali per
     * proses — restart service dalam proses yang sama tidak memutar ulang. */
    private fun maybePlayPromoOnColdBoot() {
        if (coldBootPromoDone) return
        if (lastPromoUrl.isBlank()) {
            coldBootPromoDone = true
            return
        }
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (!pm.isInteractive) return
        coldBootPromoDone = true
        wakePromoArmed = false
        mainHandler.postDelayed({
            if (lastPromoUrl.isNotBlank() && pm.isInteractive) {
                MediaActivity.start(this, lastPromoType, lastPromoUrl)
            }
        }, 2000)
    }

    /** Kabari server kasir kondisi layar TV (untuk status HIDUP/MATI & auto-off). */
    private fun sendScreenState(screenOn: Boolean) {
        val w = ws ?: return
        val json = JSONObject()
            .put("type", "SCREEN_STATE")
            .put("meja_id", lastMeja)
            .put("screen_on", screenOn)
        w.sendRaw(json.toString())
    }

    // ── Keep-alive saat HDMI pindah / display off ────────────────────────────
    // Partial wake lock + wifi lock: CPU & jaringan tetap jalan walau layar TV
    // dialihkan ke input HDMI lain (proses di STB tidak mati).
    private fun acquireKeepAlive() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "rrbilling:keepalive")
                .apply { acquire() }
        } catch (_: Exception) {
        }
        try {
            val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION")
            wifiLock = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "rrbilling:keepalive")
                .apply { acquire() }
        } catch (_: Exception) {
        }
    }

    private fun releaseKeepAlive() {
        try {
            if (wakeLock?.isHeld == true) wakeLock?.release()
        } catch (_: Exception) {
        }
        try {
            if (wifiLock?.isHeld == true) wifiLock?.release()
        } catch (_: Exception) {
        }
        wakeLock = null
        wifiLock = null
    }

    // ── Setup ────────────────────────────────────────────────────────────────
    private fun ensureRunning() {
        if (ws != null) return
        acquireKeepAlive()

        val host = Prefs.host(this)
        val port = Prefs.port(this)
        val mejaId = Prefs.mejaId(this)

        overlay = OverlayWidget(this)
        pinOverlay = PinOverlay(this)

        timer = TimerEngine(
            onTick = { remaining -> updateTimerUi(remaining) },
            onFinished = { autoLock() },
        )

        ws = WebSocketManager(
            host = host,
            port = port,
            mejaId = mejaId,
            onMessage = { msg -> handleServerMessage(msg) },
            onStatusChanged = { connected -> notifyStatus(connected) },
        ).also { it.start() }

        startOverlayHealthCheck()
        updateNotification("Terhubung ke $host:$port")
    }

    private fun stopTimerAndWs() {
        stopOverlayHealthCheck()
        timer?.stop()
        ws?.stop()
        ws = null
    }

    /** Health-check berkala: re-show overlay bila sesi berjalan tapi overlay
     * menghilang (ROM agresif mematikan window / addView gagal transien).
     * Dijalankan di main thread (semua operasi window manager harus di sini). */
    private fun startOverlayHealthCheck() {
        val runnable = object : Runnable {
            override fun run() {
                try {
                    val t = timer
                    if (t != null && t.state != TimerEngine.State.STOPPED &&
                        ws?.connected == true
                    ) {
                        updateTimerUi(t.remainingSeconds)
                    }
                } catch (_: Exception) {
                }
                mainHandler.postDelayed(this, 30_000L)
            }
        }
        healthCheck?.let { mainHandler.removeCallbacks(it) }
        healthCheck = runnable
        mainHandler.postDelayed(runnable, 30_000L)
    }

    private fun stopOverlayHealthCheck() {
        healthCheck?.let { mainHandler.removeCallbacks(it) }
        healthCheck = null
    }

    // ── Foreground notification ──────────────────────────────────────────────
    private fun startInForeground() {
        val channelId = "rr_tv_service"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(
                NotificationChannel(channelId, getString(R.string.notification_channel_name),
                    NotificationManager.IMPORTANCE_LOW)
            )
        }

        val pi = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = notificationBuilder(channelId, getString(R.string.notification_text))
            .setContentIntent(pi)
            .setOngoing(true)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, notification)
        }
    }

    private fun updateNotification(text: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.notify(1, notificationBuilder("rr_tv_service", text).build())
        }
    }

    private fun notificationBuilder(channelId: String, text: String): Notification.Builder {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, channelId)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(text)
    }

    // ── Parser pesan dari server kasir ───────────────────────────────────────
    private fun handleServerMessage(msg: ServerMessage) {
        // Pesan tiba di thread OkHttp — semua operasi UI (overlay, activity,
        // timer) harus di main thread, kalau tidak wm.addView crash.
        mainHandler.post { dispatchServerMessage(msg) }
    }

    private fun dispatchServerMessage(msg: ServerMessage) {
        when (msg.action) {
            Actions.START_TIMER -> {
                lastTotal = msg.totalTagihan.ifBlank { "Rp 0" }
                lastLunas = msg.lunasTotal
                lastTagihan = msg.tagihanTotal
                lastMeja = msg.mejaId.ifBlank { lastMeja }
                lastRental = msg.namaRental.ifBlank { lastRental }
                // R3: lastPromoUrl TIDAK dihapus saat sesi mulai — promo tetap
                // diputar 1x setiap TV bangun dari tidur walau ada sesi berjalan.
                applyOverlayConfig(msg.overlayMode, msg.overlayLastMinutes)
                setLocked(false, null)
                overlay?.show(msg.mejaId, msg.namaRental, msg.totalTagihan,
                    msg.lunasTotal, msg.tagihanTotal)
                timer?.start(msg.sisaDetik)
                updateTimerUi(msg.sisaDetik)
                updateNotification("${msg.mejaId} — ${OverlayWidget.formatHms(msg.sisaDetik)}")
                if (!OverlayPermission.isGranted(this)) {
                    updateNotification("⚠ Izin overlay belum aktif — aktifkan di Pengaturan")
                }
            }

            Actions.PAUSE_TIMER -> {
                timer?.pause()
            }

            Actions.RESUME_TIMER -> {
                timer?.resume(msg.sisaDetik)
            }

            Actions.STOP_TIMER -> {
                timer?.stop()
                overlay?.hide()
                setLocked(false, null)
            }

            Actions.UPDATE_TOTAL -> {
                // Total berjalan Main Bebas: diperbarui kasir tiap detik.
                lastTotal = msg.totalTagihan.ifBlank { lastTotal }
                if (msg.lunasTotal.isNotBlank()) lastLunas = msg.lunasTotal
                if (msg.tagihanTotal.isNotBlank()) lastTagihan = msg.tagihanTotal
                overlay?.updateBill(msg.totalTagihan, msg.lunasTotal, msg.tagihanTotal)
            }

            Actions.SYNC_TIMER -> {
                // Sinkronisasi sisa waktu + total dari kasir (dikirim tiap detik).
                applyOverlayConfig(msg.overlayMode, msg.overlayLastMinutes)
                if (msg.totalTagihan.isNotBlank()) {
                    lastTotal = msg.totalTagihan
                    if (msg.lunasTotal.isNotBlank()) lastLunas = msg.lunasTotal
                    if (msg.tagihanTotal.isNotBlank()) lastTagihan = msg.tagihanTotal
                    overlay?.updateBill(msg.totalTagihan, msg.lunasTotal, msg.tagihanTotal)
                }
                timer?.sync(msg.sisaDetik)
            }

            Actions.LOCK_SCREEN -> {
                timer?.stop()
                overlay?.hide()
                lastPromoUrl = msg.detail?.promoUrl ?: ""
                Prefs.savePromo(this, lastPromoUrl, lastPromoType)
                setLocked(true, msg.detail ?: LockDetail(msg.mejaId, "-", "Rp 0", "Rp 0"))
            }

            Actions.UNLOCK_SCREEN -> {
                setLocked(false, null)
            }

            Actions.UPDATE_LOGO -> {
                // Logo lock diganti kasir (tombol LOGO / Ganti Logo Lock):
                // refresh langsung lockscreen yang sedang tampil.
                if (locked && msg.logoUrl.isNotBlank()) {
                    val cur = lockDetail
                    if (cur != null) {
                        val updated = cur.copy(logoUrl = msg.logoUrl)
                        lockDetail = updated
                        LockScreenActivity.updateDetail(updated)
                    }
                }
            }

            Actions.UPDATE_RENTAL -> {
                // Nama rental (popup kanan atas) diganti kasir dari Profil.
                if (msg.namaRental.isNotBlank()) {
                    lastRental = msg.namaRental
                    overlay?.updateRental(msg.namaRental)
                }
            }

            Actions.SHOW_MEDIA -> {
                if (msg.mediaUrl.isNotBlank()) {
                    // Arm promo untuk diputar 1x saat TV bangun dari tidur
                    // (media terakhir, video ATAU gambar — sampai media baru).
                    lastPromoUrl = msg.mediaUrl
                    lastPromoType = msg.mediaType.ifBlank { "video" }
                    Prefs.savePromo(this, lastPromoUrl, lastPromoType)
                    MediaActivity.start(this, msg.mediaType, msg.mediaUrl)
                    updateNotification("Media: ${msg.mediaType}")
                }
            }

            Actions.HIDE_MEDIA -> {
                MediaActivity.finishInstance()
            }

            Actions.SHOW_PIN -> {
                if (msg.pin.isNotBlank()) {
                    pinOverlay?.show(msg.pin, msg.mejaId)
                }
            }

            Actions.HIDE_PIN -> {
                pinOverlay?.hide()
            }

            else -> Unit
        }
    }

    // ── Timer / overlay UI ───────────────────────────────────────────────────
    private fun applyOverlayConfig(mode: String, lastMinutes: Int) {
        if (mode.isNotBlank()) overlayMode = mode
        if (lastMinutes >= 1) overlayLastMinutes = lastMinutes
    }

    private fun updateTimerUi(remaining: Int) {
        val bebas = timer?.isBebas() == true
        if (bebas) {
            // Main Bebas (∞) — overlay selalu tampil di mode apapun.
            ensureOverlayVisible()
            overlay?.updateTimer("∞ BEBAS")
            overlay?.updateBill(lastTotal, lastLunas, lastTagihan)
        } else {
            val visible = when (overlayMode) {
                "hidden" -> false
                "last_minutes" -> remaining >= 0 && remaining <= overlayLastMinutes * 60
                else -> true
            }
            if (visible) {
                ensureOverlayVisible()
                overlay?.updateTimer(OverlayWidget.formatHms(remaining))
            } else {
                overlay?.hide()
            }
        }
        if (remaining <= 0 && !bebas) updateNotification("Waktu habis")
    }

    private fun ensureOverlayVisible() {
        val o = overlay ?: return
        if (!o.isShowing) o.show(lastMeja, lastRental, lastTotal, lastLunas, lastTagihan)
    }

    private fun autoLock() {
        overlay?.hide()
        // Pakai detail dari server bila ada; kalau belum sempat tiba, pakai
        // total terakhir yang diketahui supaya tidak tampil "Rp 0".
        val detail = lockDetail ?: LockDetail(
            lastMeja, "-", "Rp 0", lastTotal,
            lunasTotal = lastLunas, tagihanTotal = lastTagihan)
        setLocked(true, detail)
    }

    private fun setLocked(value: Boolean, detail: LockDetail?) {
        if (locked == value && lockDetail == detail) return
        val wasLocked = locked
        locked = value
        lockDetail = detail
        if (value) {
            if (wasLocked) {
                // Lockscreen sudah tampil (mis. autoLock saat countdown habis):
                // jangan buka activity baru — cukup perbarui isinya dengan
                // detail terbaru dari server (total valid saat waktu habis).
                LockScreenActivity.updateDetail(detail)
            } else {
                LockScreenActivity.start(this, detail)
            }
        } else {
            LockScreenActivity.finishInstance()
        }
        notifyLock(value)
    }

    // ── State access (untuk LockScreenActivity & MainActivity) ───────────────
    val isLocked: Boolean get() = locked
    val currentLockDetail: LockDetail? get() = lockDetail
    val isConnected: Boolean get() = ws?.connected == true

    fun addListener(l: StateListener) {
        listeners.add(l)
    }

    fun removeListener(l: StateListener) {
        listeners.remove(l)
    }

    private fun notifyLock(value: Boolean) {
        val copy = listeners.toList()
        for (l in copy) l.onLockChanged(value)
    }

    private fun notifyStatus(value: Boolean) {
        if (value) {
            // Saat (re)connect: kirim status layar terkini supaya server langsung
            // tahu TV hidup/mati tanpa menunggu broadcast berikutnya.
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            sendScreenState(pm.isInteractive)
        }
        val copy = listeners.toList()
        for (l in copy) l.onStatusChanged(value)
    }

    companion object {
        @Volatile
        var instance: TvOverlayService? = null
            private set

        fun start(context: Context) {
            val intent = Intent(context, TvOverlayService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                @Suppress("DEPRECATION")
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, TvOverlayService::class.java))
        }

        fun isRunning(context: Context): Boolean {
            val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            @Suppress("DEPRECATION")
            val services = am.getRunningServices(100)
            return services.any { it.service.className == TvOverlayService::class.java.name }
        }
    }
}
