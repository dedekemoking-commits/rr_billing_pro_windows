package com.rrbillingpro.tvclient.service

import android.app.ActivityManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.app.admin.DevicePolicyManager
import android.content.BroadcastReceiver
import android.content.ComponentName
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
import android.os.SystemClock
import android.util.Log
import com.rrbillingpro.tvclient.KioskAdminReceiver
import com.rrbillingpro.tvclient.MainActivity
import com.rrbillingpro.tvclient.R
import com.rrbillingpro.tvclient.media.MediaPickerActivity
import com.rrbillingpro.tvclient.media.MediaActivity
import com.rrbillingpro.tvclient.lockscreen.LockScreenActivity
import com.rrbillingpro.tvclient.model.Actions
import com.rrbillingpro.tvclient.model.LockDetail
import com.rrbillingpro.tvclient.model.ServerMessage
import com.rrbillingpro.tvclient.net.MediaUploadServer
import com.rrbillingpro.tvclient.net.TimerEngine
import com.rrbillingpro.tvclient.net.WebSocketManager
import com.rrbillingpro.tvclient.net.HubAdvertListener
import com.rrbillingpro.tvclient.overlay.MessageOverlay
import com.rrbillingpro.tvclient.overlay.OverlayWidget
import com.rrbillingpro.tvclient.overlay.PinOverlay
import com.rrbillingpro.tvclient.overlay.QrOverlay
import com.rrbillingpro.tvclient.permission.OverlayPermission
import com.rrbillingpro.tvclient.util.NetUtil
import com.rrbillingpro.tvclient.util.Prefs
import org.json.JSONArray
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
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
    private var qrOverlay: QrOverlay? = null
    private var messageOverlay: MessageOverlay? = null
    private var timer: TimerEngine? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var screenWakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var mediaServer: MediaUploadServer? = null
    private var sleepRunnable: Runnable? = null
    private var eventPopupUntilMs = 0L
    private var eventPopupRunnable: Runnable? = null

    @Volatile
    private var sessionActive = false

    // Health-check overlay (interval 30 dtk): jika sesi berjalan tapi overlay
    // tidak tampil (mis. addView ditolak sekali / di-hide oleh ROM ketat seperti
    // TCL), langsung re-show dari state terakhir — tidak menunggu pesan server.
    private var healthCheck: Runnable? = null

    // Callback fallback lockscreen dari Prefs (status lokal usang).
    private var pendingLockFallback: Runnable? = null

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

    @Volatile
    private var isLastTime: Boolean = false

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
    // tidak menyebabkan dobel putar. Bangun TANPA SCREEN_OFF (perintah WAKEUP
    // kasir, layar dinyalakan promo lain, HDMI-CEC) tetap memutar promo:
    // pembendungnya promoMulaiMs di bawah, bukan kunci ini.
    private var wakePromoArmed = true

    // Waktu (elapsedRealtime) promo terakhir mulai — pembendung SCREEN_ON
    // ganda pasca-boot saat SCREEN_OFF tidak pernah diterima (firmware/STB
    // kadang tidak mengirim ACTION_SCREEN_OFF). SCREEN_ON dalam jendela
    // PROMO_DEDUP_MS setelah promo mulai dianggap event ganda, bukan bangun.
    private var promoMulaiMs = 0L

    // ACTION_SCREEN_ON kadang tiba sebelum isInteractive berubah true (khas
    // setelah perintah WAKEUP). Retry sesaat tanpa mengonsumsi kunci promo;
    // lewat batas ini baru dilaporkan sebagai gagal.
    private var layarNyalaUlangSampaiMs = 0L

    // Kasir sedang pairing TV ini: promo, power key, lockscreen, dan overlay
    //_dimatikan supaya dialog kode pairing sistem tidak ikut hilang.
    @Volatile
    private var pairingMode = false

    // ── Persistensi sesi & kunci offline (v4.14) ─────────────────────────────
    // Snapshot sesi terakhir disimpan ke Prefs (START/PAUSE/SYNC + saat TV
    // tidur). Saat CLI putus / TV mati-nyala, popup waktu dipulihkan lokal &
    // countdown lanjut; TimerEngine mengunci sendiri saat habis (grace 20 dtk).
    // Snapshot yang sudah kedaluwarsa saat dipulihkan DIBUANG tanpa kunci
    // (keputusan pemilik: promo dulu, lalu TV bebas).
    private var sesiPulihRemain = -1
    private var sesiPulihPaused = false
    private var sesiPulihBebas = false
    private var lastSesiSaveMs = 0L
    // Bangun dengan status TERKUNCI dari Prefs + CLI offline: promo tetap
    // diputar, lalu kunci dibuka lokal (v4.14, keputusan pemilik).
    private var offlineUnlockPending = false
    // Main Bebas: hitung detik berjalan lokal saat CLI offline (online, nilai
    // otoritatif datang dari server tiap detik).
    private var bebasTicker: Runnable? = null

    // Auto-discovery hub (v4.14): kasir memancarkan alamatnya via UDP; listener
    // memindahkan TV ke alamat baru + reconnect otomatis (ganti IP PC, DHCP).
    private var hubAdvert: HubAdvertListener? = null
    private var lastAdvertRebuildMs = 0L
    private var lastWsConnectedMs = 0L
    private var lastWsDisconnectedMs = 0L

    private var screenReceiver: BroadcastReceiver? = null

    // Reporter logcat untuk RR Monitor: kirim error terbaru ke kasir.
    private var logReportRunnable: Runnable? = null
    @Volatile private var lastLogHash: Int = 0
    @Volatile private var lastLogSentMs: Long = 0L

    private val logReportThreadPool: ThreadPoolExecutor by lazy {
        ThreadPoolExecutor(
            2, 4, 60L, TimeUnit.SECONDS,
            LinkedBlockingQueue(10)
        )
    }

    @Volatile private var mejaId: String = "MEJA"

    private val listeners = mutableListOf<StateListener>()

    interface StateListener {
        fun onLockChanged(locked: Boolean)
        fun onStatusChanged(connected: Boolean)
    }

    override fun onCreate() {
        super.onCreate()
        TvOverlayService.instance = this
        promptRemoveLegacyClient()
        lastStyle = Prefs.overlayStyle(this)
        overlayMode = Prefs.overlayMode(this)
        overlayLastMinutes = Prefs.overlayLastMinutes(this)
        bebasStartDurasi = Prefs.bebasStartDurasi(this)
        bebasInterval = Prefs.bebasInterval(this)
        bebasDurasi = Prefs.bebasDurasi(this)
        lastMeja = Prefs.mejaId(this).ifBlank { "MEJA" }
        // Restore promo terakhir agar tetap diputar 1x setelah TV reboot total
        // (mati listrik / cold boot) — URL terakhir tersimpan di Prefs.
        lastPromoUrl = Prefs.promoUrl(this)
        lastPromoType = Prefs.promoType(this)
        // Restore status lock SETELAH reboot/TV mati-nyala. Prefs adalah
        // status LAMA (bisa usang), jadi tunda: beri server kesempatan
        // mengirim snapshot terbaru dulu. Jika server tidak menjawab
        // dalam batas waktu, baru kunci dari Prefs (fallback anti-curi).
        if (Prefs.isLocked(this)) {
            locked = true
            lockDetail = Prefs.lockDetail(this)
            scheduleLockFallback(8000)
        } else {
            // v4.14: sesi terakhir (sisa sewa, total, meja, gaya overlay)
            // dipulihkan dari Prefs. Kedaluwarsa saat TV mati = dibuang tanpa
            // kunci; masih berjalan = popup tampil lagi & countdown lanjut.
            pulihkanSesiLokal()
        }
        com.rrbillingpro.tvclient.KioskAdminReceiver.allowSelfLockTask(this)
        startInForeground()
        registerScreenReceiver()
        // Auto-discovery hub: dengar alamat kasir dari UDP broadcast supaya
        // ganti IP PC tidak membuat TV buta (v4.14).
        mulaiDiscoveryHub()
    }

    fun onMediaPicked(name: String, mediaType: String) {
        val w = ws ?: return
        try {
            val json = JSONObject()
                .put("type", "MEDIA_PICKED")
                .put("meja_id", Prefs.mejaId(this))
                .put("name", name)
                .put("media_type", mediaType)
            w.sendRaw(json.toString())
            Log.d("RRTVService", "OK [MEDIA_PICKED]")
        } catch (_: Exception) {
            Log.w("RRTVService", "GAGAL [MEDIA_PICKED]")
        }
    }

    private fun promptRemoveLegacyClient() {
        val legacy = "com.billingps.tvclient"
        val installed = try {
            @Suppress("DEPRECATION")
            packageManager.getPackageInfo(legacy, 0)
            true
        } catch (_: Exception) {
            false
        }
        if (!installed || Prefs.legacyUninstallPrompted(this)) return
        try {
            startActivity(
                Intent(Intent.ACTION_UNINSTALL_PACKAGE, android.net.Uri.parse("package:$legacy"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
            Prefs.setLegacyUninstallPrompted(this)
            android.util.Log.i("RRTVService", "Prompt hapus client lama ditampilkan")
        } catch (e: Exception) {
            android.util.Log.w("RRTVService", "Gagal prompt hapus client lama: ${e.message}")
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startInForeground()
        ensureRunning()
        maybePlayPromoOnColdBoot()
        // Popup yang dipulihkan baru bisa ditampilkan setelah overlay & timer
        // dibuat (ensureRunning), dan setelah promo cold-boot dijadwalkan.
        if (layarNyala()) {
            mainHandler.postDelayed({
                if (!pairingMode) refreshOverlayPascaBangun()
            }, 800)
        }
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
        cancelScheduledSleep()
        eventPopupRunnable?.let { mainHandler.removeCallbacks(it) }
        eventPopupRunnable = null
        hubAdvert?.stop()
        hubAdvert = null
        unregisterScreenReceiver()
        releaseKeepAlive()
        stopTimerAndWs()
        overlay?.hide()
        pinOverlay?.hide()
        qrOverlay?.hide()
        messageOverlay?.hide()
        super.onDestroy()
        if (TvOverlayService.instance === this) TvOverlayService.instance = null
    }

    private fun stopTimerAndWs() {
        stopOverlayHealthCheck()
        statusHeartbeat?.let { mainHandler.removeCallbacks(it) }
        statusHeartbeat = null
        stopLogReporter()
        timer?.stop()
        timer = null
        ws?.stop()
        ws = null
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
                            if (sessionActive) setSessionScreenOn(true)
                            sendScreenState(true)
                            laporkanKeKasir("tv_bangun", true,
                                            "TV hidup (layar menyala)")
                            if (locked) {
                                // `locked` di sini bisa status LAMA dari Prefs.
                                // Beri server 4 dtk mengirim snapshot terbaru
                                // (REGISTER) setelah forceReconnect:
                                //   - CLI hidup  -> snapshot server menentukan
                                //     (perilaku lama: fallback lockscreen Prefs).
                                //   - CLI OFFLINE -> promo tetap diputar, lalu
                                //     kunci dibuka lokal (keputusan pemilik).
                                ws?.forceReconnect()
                                mainHandler.postDelayed({
                                    if (pairingMode || !locked) return@postDelayed
                                    if (ws?.connected == true) {
                                        scheduleLockFallback(5000)
                                    } else {
                                        Log.i("RRTVService", "bangun saat CLI offline " +
                                                "& terkunci — promo + buka kunci lokal")
                                        cancelLockFallback()
                                        offlineUnlockPending = true
                                        wakePromoArmed = true
                                        onScreenWake()
                                        mainHandler.postDelayed({
                                            if (offlineUnlockPending && !pairingMode &&
                                                    MediaActivity.instance == null) {
                                                bukaKunciOffline()
                                            }
                                        }, 1500)
                                    }
                                }, 4000)
                            } else {
                                onScreenWake()
                                mainHandler.postDelayed({
                                    if (!locked && !pairingMode && layarNyala()) {
                                        refreshOverlayPascaBangun()
                                    }
                                }, 400)
                            }
                        }
                        Intent.ACTION_SCREEN_OFF -> {
                            // Ingat port HDMI yang sedang dipakai SEBELUM tidur.
                            // Banyak firmware STB me-reset
                            // `tv_last_used_input_id` jadi kosong begitu bangun,
                            // sehingga tanpa catatan ini app tidak tahu port mana
                            // yang benar — dan kalau asal menebak, pelanggan
                            // dikirim ke port kosong (layar hitam).
                            simpanPortSebelumTidur()
                            // v4.14: simpan juga snapshot sesi (sisa waktu
                            // terakhir) supaya popup & countdown tetap hidup
                            // walau proses app mati selama TV tidur.
                            simpanSesiLokal(paksa = true)
                            releaseSessionScreen()
                            wakePromoArmed = true
                            // Banner pesan kasir tidak boleh nyangkut menutupi
                            // layar saat TV bangun lagi — hilangkan sekarang.
                            messageOverlay?.hide()
                            sendScreenState(false)
                            laporkanKeKasir("tv_tidur", true,
                                            "TV masuk sleep (layar mati)")
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

    /**
     * Simpan port HDMI yang sedang aktif ke Prefs saat TV mau tidur.
     *
     * Ini satu-satunya catatan port yang bertahan setelah tidur, karena
     * `tv_last_used_input_id` di banyak STB (MediaTek, Realtek, Hisilicon,
     * Amlogic, ...) dikosongkan ulang ketika bangun. Tanpa catatan ini,
     * promo yang diputar setelah bangun tidak tahu harus kembali ke mana —
     * dulu app asal menebak HDMI pertama, hasilnya layar hitam.
     */
    private fun simpanPortSebelumTidur() {
        try {
            val id = android.provider.Settings.Secure.getString(
                contentResolver, "tv_last_used_input_id")?.trim()
            if (!id.isNullOrEmpty()) {
                Prefs.saveLastInput(this, id)
                Log.i("RRTVService", "port sebelum tidur disimpan: $id")
            } else {
                Log.w("RRTVService", "port sebelum tidur tidak terbaca (TV di Home?)")
            }
        } catch (e: Exception) {
            Log.w("RRTVService", "gagal menyimpan port sebelum tidur: ${e.message}")
        }
    }

    // Layar STB menyala dan bisa dipakai (isInteractive)?
    private fun layarNyala(): Boolean {
        val pm = getSystemService(Context.POWER_SERVICE) as? PowerManager
        return try { pm?.isInteractive == true } catch (_: Exception) { false }
    }

    /** Kirim state layar ke server kasir. */
    private fun sendScreenState(screenOn: Boolean) {
        val w = ws ?: return
        val json = JSONObject()
            .put("type", "SCREEN_STATE")
            .put("meja_id", lastMeja)
            .put("screen_on", screenOn)
            .put("input_label", currentInputLabel())
            .put("input_label", currentInputLabel())
        w.sendRaw(json.toString())
        Log.d("RRTVService", "SCREEN_STATE: on=$screenOn input=${currentInputLabel()} mode=unknown")
    }

    private fun unregisterScreenReceiver() {        try {
            if (screenReceiver != null) {
                unregisterReceiver(screenReceiver)
                screenReceiver = null
            }
        } catch (_: Exception) {
        }
    }

    // ── Auto-discovery hub (v4.14) ───────────────────────────────────────────
    private fun mulaiDiscoveryHub() {
        if (hubAdvert != null) return
        hubAdvert = HubAdvertListener { host, port ->
            // Dipanggil dari thread UDP — pindah ke main thread.
            mainHandler.post { terapkanAlamatHubBaru(host, port) }
        }.also { it.start() }
    }

    /**
     * Hub ditemukan di alamat lain: simpan + bangun ulang koneksi WS.
     * Snapshot sesi (kalau server sedang menjalankan sesi) otomatis dikirim
     * server begitu TV terdaftar kembali.
     */
    private fun terapkanAlamatHubBaru(host: String, port: Int) {
        val curH = Prefs.host(this)
        val curP = Prefs.port(this)
        if (host == curH && port == curP) return
        val now = System.currentTimeMillis()
        // Jangan pindah hub saat koneksi masih sehat. Di jaringan dengan lebih
        // dari satu kasir, broadcast yang datang bergantian membuat TV
        // berpindah-pindah tiap 15 detik dan timer/log ikut terputus.
        if (ws?.connected == true) return
        if (lastWsDisconnectedMs > 0 && now - lastWsDisconnectedMs < 15_000L) return
        if (lastWsConnectedMs == 0L && now - lastAdvertRebuildMs < 15_000L) return
        if (now - lastAdvertRebuildMs < 15_000L) return
        lastAdvertRebuildMs = now
        Log.i("RRTVService", "hub ditemukan via UDP: $host:$port " +
                "(sebelumnya $curH:$curP) — pindah & reconnect")
        laporkanKeKasirLama("tv_hub_pindah", true,
                "alamat hub berubah via discovery: $curH:$curP -> $host:$port")
        Prefs.save(this, host, port, Prefs.mejaId(this), Prefs.autoStart(this))
        updateNotification("Menghubungkan ke $host:$port")
        // Ganti HANYA manager WS — timer/overlay/sesi lokal (termasuk snapshot
        // offline) tidak boleh terganggu oleh pindah alamat.
        gantiManagerWs(host, port)
    }

    /** Bangun ulang WebSocketManager ke alamat baru tanpa menyentuh timer. */
    private fun gantiManagerWs(host: String, port: Int) {
        try {
            ws?.stop()
        } catch (_: Exception) {
        }
        ws = WebSocketManager(
            host = host,
            port = port,
            mejaId = Prefs.mejaId(this),
            appContext = applicationContext,
            onMessage = { msg -> handleServerMessage(msg) },
            onStatusChanged = { connected -> notifyStatus(connected) },
        ).also { it.start() }
    }

    /**
     * Laporan khusus saat pindah alamat: WS utama mungkin masih menunjuk
     * alamat lama, jadi coba lewat manager yang ada dulu (kalau kebetulan
     * server baru = lama), kalau tidak hanya tulis log.
     */
    private fun laporkanKeKasirLama(aksi: String, ok: Boolean, pesan: String) {
        try {
            if (ws?.connected == true) laporkanKeKasir(aksi, ok, pesan)
            else Log.i("RRTVService", "lapor $aksi: $pesan (CLI offline)")
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
        // Sedang pairing: JANGAN sentuh layar. Promo fullscreen menutupi dialog
        // kode pairing sistem sehingga TV memutus koneksi pairing dan PIN yang
        // diklik kasir gagal ("Connection has been lost").
        if (pairingMode) {
            wakePromoArmed = false
            Log.d("RRTVService", "onScreenWake: skip (pairing mode)")
            return
        }
        if (!wakePromoArmed) return
        wakePromoArmed = false

        // ACTION_SCREEN_ON sudah berarti layar menyala, jadi tidak ada yang perlu
        // "dibangunkan" di sini. Dulu service mengirim `input keyevent 26`
        // (KEYCODE_POWER) hoping layar terbuild, padahal perintah itu butuh
        // izin INJECT_EVENTS yang tidak dimiliki app ini — jadi diam-diam gagal
        // (lihat log "Failed to send power key"). Menyalakan layar bukan duty
        // service: MediaActivity memakai setTurnScreenOn/setShowWhenLocked.
        if (!layarNyala()) {
            // Khas setelah perintah WAKEUP kasir: broadcast tiba sebelum
            // isInteractive berubah true. Jangan konsumsi kunci promo —
            // retry sesaat supaya promo tidak dilewatkan percuma.
            val now = SystemClock.elapsedRealtime()
            if (layarNyalaUlangSampaiMs == 0L) {
                layarNyalaUlangSampaiMs = now + 2_000L
            }
            if (now < layarNyalaUlangSampaiMs) {
                Log.d("RRTVService", "onScreenWake: layar belum interactive — retry")
                mainHandler.postDelayed({ onScreenWake() }, 300)
                return
            }
            layarNyalaUlangSampaiMs = 0L
            Log.d("RRTVService", "onScreenWake: layar belum interactive, promo dilewati")
            laporkanKeKasir("tv_bangun", true,
                            "TV hidup tapi layar belum menyala — promo dilewati")
            return
        }
        layarNyalaUlangSampaiMs = 0L

        val baruBangun = wakePromoArmed
        wakePromoArmed = false
        // SCREEN_ON bisa datang TANPA didahului SCREEN_OFF — layar dinyalakan
        // promo yang sedang jalan (SHOW_MEDIA R4 saat connect), perintah
        // WAKEUP kasir, atau firmware yang tidak mengirim SCREEN_OFF saat
        // stand-by. Jendela promoMulaiMs hanya membendung SCREEN_ON ganda
        // pasca-boot; di luar jendela itu bangun asli tetap WAJIB memutar
        // promo walau kunci sudah habis.
        if (!baruBangun && MediaActivity.instance == null &&
            SystemClock.elapsedRealtime() - promoMulaiMs < TvOverlayService.PROMO_DEDUP_MS) {
            Log.d("RRTVService", "onScreenWake: SCREEN_ON ganda (promo baru saja mulai) — dilewati")
            return
        }

        // v4.13: promo lokal menggantikan URL kosong. Kalau TIDAK ada aset
        // lokal sama sekali DAN tidak ada URL terakhir, jangan pernah mulai
        // MediaActivity kosong — layar hitam/activity "kedip" 1 detik yang
        // dilihat pelanggan saat TV bangun justru berasal dari sini.
        val adaLokal = Prefs.adaMediaLokal(this, "promo.mp4") ||
                Prefs.adaMediaLokal(this, "promo.jpg")
        if (lastPromoUrl.isBlank() && !adaLokal) {
            Log.d("RRTVService", "onScreenWake: tidak ada promo (lokal/URL kosong) — dilewati")
            return
        }
        mainHandler.postDelayed({
            // Promo boleh saja sudah tampil (kasir bisa saja mengirim SHOW_MEDIA
            // bersamaan) — jangan dobel start.
            if (MediaActivity.instance == null && layarNyala()) {
                promoMulaiMs = SystemClock.elapsedRealtime()
                MediaActivity.start(this, lastPromoType, lastPromoUrl)
            }
        }, 100)
    }

    /** Cold boot / service mulai dengan layar sudah menyala: ACTION_SCREEN_ON
     * tidak pernah diterima (event terjadi sebelum proses lahir), jadi promo
     * terakhir (tersimpan di Prefs) diputar 1x di sini. Hanya sekali per
     * proses — restart service dalam proses yang sama tidak memutar ulang. */
    private fun maybePlayPromoOnColdBoot() {
        if (coldBootPromoDone) return
        if (pairingMode) {
            Log.d("RRTVService", "cold boot promo: skip (pairing mode)")
            return
        }
        // Layar mati = tidak ada yang bisa ditonton. Promo tidak diputar di sini;
        // nanti diputar 1x saat ACTION_SCREEN_ON benar-benar datang.
        if (!layarNyala()) {
            Log.d("RRTVService", "cold boot promo: layar mati, tunggu SCREEN_ON")
            return
        }
        coldBootPromoDone = true
        wakePromoArmed = false
        val adaLokal = Prefs.adaMediaLokal(this, "promo.mp4") ||
                Prefs.adaMediaLokal(this, "promo.jpg")
        if (lastPromoUrl.isBlank() && !adaLokal) {
            Log.d("RRTVService", "cold boot promo: tidak ada promo (lokal/URL kosong) — dilewati")
            return
        }
        // Jeda diperpendek (dulu 2000ms): makin cepat frame promo tampil,
        // makin kecil peluang pelanggan melihat launcher/app sekilas.
        mainHandler.postDelayed({
            if (MediaActivity.instance == null && layarNyala()) {
                promoMulaiMs = SystemClock.elapsedRealtime()
                MediaActivity.start(this, lastPromoType, lastPromoUrl)
            }
        }, 300)
    }

    /**
     * Kabari server kasir kondisi TV: HIDUP/MATI + port input yang sedang
     * dipakai (HDMI1/2/... atau HOME) + mode layar (promo/lock/input).
     * Kasir memakai ini untuk displays status di kartu TV dan memberi
     * peringatan bila TV keluar jalur (mis. bangun tapi tidak merespons).
     */

    /** True bila LockScreenActivity benar-benar masih hidup di layar. */
    fun lockScreenVisible(): Boolean = LockScreenActivity.isAlive()

    /**
     * Nama input TV yang sedang dipakai: "HDMI1", "HDMI2", dst.
     *
     * PENTING: Prefs "last input" TIDAK boleh jadi sumber utama. Nilai itu
     * hanya berisi port yang terakhir dipakai saat promo selesai, dan tidak
     * pernah berubah ketika pelanggan memindahkan HDMI sendiri atau kembali
     * ke Home Android — akibatnya kasir ikut menampilkan port yang salah.
     * Sumber utama sekarang adalah Settings.Secure milik sistem Android TV;
     * Prefs hanya cadangan terakhir.
     *
     * Kosong = tidak ada port HDMI yang bisa dibaca (mis. sedang di Home).
     */
    private fun currentInputLabel(): String {
        try {
            val sys = android.provider.Settings.Secure.getString(
                contentResolver, "tv_last_used_input_id")
            if (sys != null) {
                // Setting ADA di firmware ini. Kosong berarti TV sedang tidak
                // memakai input HDMI apa pun (mis. sudah di Home Android) —
                // itu kondisi nyata, jadi JANGAN jatuh ke Prefs lama.
                return if (sys.isBlank()) "" else prettyInputLabel(sys)
            }
        } catch (_: Exception) {
        }
        // Setting tidak tersedia di firmware ini -> pakai catatan lokal
        // (port terakhir yang dipakai saat promo selesai).
        val saved = Prefs.getLastInput(this)
        if (saved.isNotBlank()) return prettyInputLabel(saved)
        return ""
    }

    /** Ubah input id sistem jadi label ramah: HDMI1, HDMI2, dst. */
    private fun prettyInputLabel(inputId: String): String {
        // Fallback: ambil angka di akhir id, mis. "HDMI1"/"hdmi_input2"
        val digits = inputId.filter { it.isDigit() }
        return if (digits.isNotEmpty()) "HDMI$digits" else inputId.uppercase()
    }

    private fun releaseSessionScreen() {
        try {
            if (screenWakeLock?.isHeld == true) screenWakeLock?.release()
        } catch (_: Exception) {
        }
        screenWakeLock = null
    }

    private fun setSessionScreenOn(active: Boolean) {
        sessionActive = active
        if (!active) {
            releaseSessionScreen()
            return
        }
        try {
            if (screenWakeLock?.isHeld == true) return
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            screenWakeLock = pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK, "rrbilling:session-screen").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (_: Exception) {
            screenWakeLock = null
        }
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
        setSessionScreenOn(false)
        try {
            if (wakeLock?.isHeld == true) wakeLock?.release()
        } catch (_: Exception) {
        }
        try {
            if (wifiLock?.isHeld == true) wifiLock?.release()
        } catch (_: Exception) {
        }
        wakeLock = null
        screenWakeLock = null
        wifiLock = null
    }

    private fun startMediaServer() {
        // Placeholder for media server startup (e.g., omxplayer / exoplayer)
        // Not implemented in this client; media playback handled via MediaActivity.
    }

    private fun startOverlayHealthCheck() {
        stopOverlayHealthCheck()
        val runnable = object : Runnable {
            override fun run() {
                try {
                    val t = timer
                    if (t != null && t.state != TimerEngine.State.STOPPED && ws?.connected == true) {
                        updateTimerUi(t.remainingSeconds)
                    }
                } catch (_: Exception) {
                }
                mainHandler.postDelayed(this, 30_000L)
            }
        }
        healthCheck = runnable
        mainHandler.postDelayed(runnable, 30_000L)
    }

    // ── Setup ────────────────────────────────────────────────────────────────
    private fun ensureRunning() {
        if (ws != null) return
        acquireKeepAlive()

        val host = Prefs.host(this)
        val port = Prefs.port(this)
        mejaId = Prefs.mejaId(this)

        overlay = OverlayWidget(this)
        pinOverlay = PinOverlay(this)
        qrOverlay = QrOverlay(this)
        messageOverlay = MessageOverlay(this)

        timer = TimerEngine(
            onTick = { remaining -> updateTimerUi(remaining) },
            onFinished = { autoLock() },
        )

        ws = WebSocketManager(
            host = host,
            port = port,
            mejaId = mejaId,
            appContext = applicationContext,
            onMessage = { msg -> handleServerMessage(msg) },
            onStatusChanged = { connected -> notifyStatus(connected) },
        ).also { it.start() }

        startMediaServer()
        startOverlayHealthCheck()
        startStatusHeartbeat()
        startLogReporter()
        updateNotification("Terhubung ke $host:$port")
    }

    /**
     * Heartbeat status tiap 15 detik: pelanggan bisa memindahkan HDMI atau
     * kembali ke Home tanpa sepengetahuan kasir, jadi laporan status harus
     * dikirim berkala — bukan hanya saat layar nyala/mati atau (re)connect.
     */
    private var statusHeartbeat: Runnable? = null

    /** Firestore sync: ringkas status perialarn (jika Firestore tersedia). */
    private fun startStatusHeartbeat() {
        statusHeartbeat?.let { mainHandler.removeCallbacks(it) }
        val r = object : Runnable {
            override fun run() {
                if (ws?.connected == true) {
                    sendScreenState(layarNyala())
                }
                sendStatusSync()
                mainHandler.postDelayed(this, 15_000L)
            }
        }
        statusHeartbeat = r
        mainHandler.postDelayed(r, 15_000L)
    }

    /** Kirim status timer + online ke server setiap 1 detik (ganti Firestore). */
    private fun sendStatusSync() {
        if (ws?.connected != true) return
        val payload = JSONObject().apply {
            put("type", "STATUS")
            put("mejaId", mejaId)
            put("app", "rrbilling-tv")
            put("online", true)
            put("syncTimer", true)
            val localRemaining = timer?.remainingSeconds ?: -1L
            put("sisaDetik", localRemaining)
            put("isWaktuDipakai", true)
        }
        ws?.sendRaw(payload.toString())
    }



    private fun stopOverlayHealthCheck() {
        healthCheck?.let { mainHandler.removeCallbacks(it) }
        healthCheck = null
    }

    // ── Reporter logcat untuk RR Monitor ─────────────────────────────────────
    private fun startLogReporter() {
        logReportRunnable?.let { mainHandler.removeCallbacks(it) }
        val runnable = object : Runnable {
            override fun run() {
                if (ws?.connected == true) collectAndSendLogs(force = false)
                mainHandler.postDelayed(this, 120_000L)
            }
        }
        logReportRunnable = runnable
        mainHandler.postDelayed(runnable, 45_000L)
    }

    private fun stopLogReporter() {
        logReportRunnable?.let { mainHandler.removeCallbacks(it) }
        logReportRunnable = null
    }

    private fun collectAndSendLogs(force: Boolean) {
        val process = try {
            Runtime.getRuntime().exec("logcat -d -v time")
        } catch (_: Exception) {
            return
        }
        val lines = process.inputStream.bufferedReader().use { it.readLines() }
        process.waitFor()
        val errors = lines.filter { isErrorLogLine(it) }.takeLast(200)
        val hash = errors.joinToString("\n").hashCode()
        val now = System.currentTimeMillis()
        if (!force && errors.isEmpty() && now - lastLogSentMs < 10 * 60 * 1000L) return
        if (!force && hash == lastLogHash && now - lastLogSentMs < 10 * 60 * 1000L) return
        lastLogHash = hash
        lastLogSentMs = now
        val arr = JSONArray()
        errors.forEach { arr.put(it.take(500)) }
        val version = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: ""
        } catch (_: Exception) {
            ""
        }
        val payload = JSONObject()
            .put("type", "LOG_REPORT")
            .put("meja_id", mejaId)
            .put("app", "rrbilling-tv")
            .put("version", version)
            .put("ts", now)
            .put("error_count", errors.size)
            .put("total_lines", lines.size)
            .put("lines", arr)
        ws?.sendRaw(payload.toString())
        Log.i("RRTVService", "LOG_REPORT terkirim: ${errors.size} error dari ${lines.size} baris")
    }

    private fun isErrorLogLine(line: String): Boolean {
        val upper = line.uppercase()
        return upper.contains(" E/") ||
            upper.contains(" E ") ||
            upper.contains("FATAL EXCEPTION") ||
            upper.contains("ANDROIDRUNTIMEEXCEPTION") ||
            upper.contains(" EXCEPTION") ||
            upper.contains(" ERROR")
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

    // ── Lockscreen fallback dari status lokal (Prefs) ──────────────────────
    // Ditampilkan hanya jika server tidak memberi state baru dalam waktu
    // terbatas (offline). Begitu pesan server tiba (START/STOP/LOCK/UNLOCK),
    // fallback dibatalkan — snapshot server adalah sumber kebenaran.
    private fun scheduleLockFallback(delayMs: Long) {
        cancelLockFallback()
        val r = Runnable {
            pendingLockFallback = null
            if (pairingMode) return@Runnable
            if (locked) {
                try { LockScreenActivity.start(this@TvOverlayService, lockDetail) } catch (_: Exception) {}
            }
        }
        pendingLockFallback = r
        mainHandler.postDelayed(r, delayMs)
    }

    private fun cancelLockFallback() {
        pendingLockFallback?.let { mainHandler.removeCallbacks(it) }
        pendingLockFallback = null
    }

    // Lokasi dispatchServerMessage
    private fun dispatchServerMessage(msg: ServerMessage) {
        Log.d("RRTVService", "action=${msg.action} sisa=${msg.sisaDetik} reconnect=${msg.reconnect}")
        if (msg.action != Actions.PING) {
            // State dari server diterima: batalkan fallback Prefs yang
            // usang — snapshot baru (START/STOP/LOCK) di bawahnya yang kini berlaku.
            cancelLockFallback()
            // Server hidup = sumber kebenaran; keputusan "buka kunci offline"
            // yang menggantung tidak berlaku lagi.
            offlineUnlockPending = false
        }
        when (msg.action) {
            Actions.START_TIMER -> {
                lastTotal = msg.totalTagihan.ifBlank { "Rp 0" }
                lastLunas = msg.lunasTotal
                lastTagihan = msg.tagihanTotal
                lastMeja = msg.mejaId.ifBlank { lastMeja }
                lastRental = msg.namaRental.ifBlank { lastRental }
                isLastTime = msg.isLastTime
                // Sesi benar-benar berjalan -> layar QR member tidak perlu lagi.
                qrOverlay?.hide()
                cancelScheduledSleep()
                // R3: lastPromoUrl TIDAK dihapus saat sesi mulai �?" promo tetap
                // diputar 1x setiap TV bangun dari tidur walau ada sesi berjalan.
                applyHdmiConfig(msg)
                applyOverlayConfig(msg.overlayMode, msg.overlayLastMinutes,
                    msg.bebasStartDurasi, msg.bebasInterval, msg.bebasDurasi)
                applyBebasConfig(msg.elapsedDetik, msg.bebasStartDurasi,
                    msg.bebasInterval, msg.bebasDurasi)
                setLocked(false, null)
                overlay?.show(msg.mejaId, msg.namaRental, msg.totalTagihan,
                    msg.lunasTotal, msg.tagihanTotal)
                if (msg.isBebas) {
                    timer?.start(-1, msg.forceStart)
                    mulaiBebasTicker()
                } else {
                    timer?.start(msg.sisaDetik, msg.forceStart)
                }
                if (!msg.noWake) setSessionScreenOn(true)
                updateTimerUi(if (msg.isBebas) -1 else msg.sisaDetik)
                updateNotification(
                    if (msg.isBebas) "${msg.mejaId} — ∞ BEBAS"
                    else "${msg.mejaId} — ${OverlayWidget.formatHms(msg.sisaDetik)}"
                )
                laporkanKeKasir(
                    "tv_overlay_timer", true,
                    "popup waktu tampil sisa=${OverlayWidget.formatHms(msg.sisaDetik)} " +
                            "mode=${msg.overlayMode} n=${msg.overlayLastMinutes} " +
                            "total=${msg.totalTagihan} lunas=${msg.lunasTotal} " +
                            "tagihan=${msg.tagihanTotal}")
                if (!OverlayPermission.isGranted(this)) {
                    updateNotification("⚠ Izin overlay belum aktif — aktifkan di Pengaturan")
                    laporkanKeKasir(
                        "tv_overlay_izin", false,
                        "Izin overlay (SYSTEM_ALERT_WINDOW) belum aktif — popup waktu tidak tampil")
                }
                // v4.14: simpan snapshot sesi (untuk pemulihan saat offline).
                simpanSesiLokal(paksa = true)
            }

            Actions.PAUSE_TIMER -> {
                timer?.pause()
                setSessionScreenOn(true)
                simpanSesiLokal(paksa = true)
                laporkanKeKasir("tv_timer_jeda", true, "sisa=${msg.sisaDetik}s")
            }

            Actions.RESUME_TIMER -> {
                timer?.resume(msg.sisaDetik)
                setSessionScreenOn(true)
                simpanSesiLokal(paksa = true)
                laporkanKeKasir("tv_timer_lanjut", true, "sisa=${msg.sisaDetik}s")
            }

            Actions.STOP_TIMER -> {
                cancelScheduledSleep()
                eventPopupUntilMs = 0L
                isLastTime = false
                setSessionScreenOn(false)
                timer?.stop()
                overlay?.hide()
                qrOverlay?.hide()
                setLocked(false, null)
                Prefs.clearSesiSnapshot(this)
                laporkanKeKasir("tv_timer_stop", true,
                                "popup waktu & QR disembunyikan, lockscreen dilepas")
            }

            Actions.UPDATE_TOTAL -> {
                // Total berjalan Main Bebas: diperbarui kasir tiap detik.
                lastTotal = msg.totalTagihan.ifBlank { lastTotal }
                if (msg.lunasTotal.isNotBlank()) lastLunas = msg.lunasTotal
                if (msg.tagihanTotal.isNotBlank()) lastTagihan = msg.tagihanTotal
                overlay?.updateBill(msg.totalTagihan, msg.lunasTotal, msg.tagihanTotal)
                if (msg.popupDetik > 0) tampilkanPopupEvent(msg.popupDetik)
                simpanSesiLokal()
            }

            Actions.SYNC_TIMER -> {
                // Sinkronisasi sisa waktu + total dari kasir (dikirim tiap detik).
                applyOverlayConfig(msg.overlayMode, msg.overlayLastMinutes,
                    msg.bebasStartDurasi, msg.bebasInterval, msg.bebasDurasi)
                applyBebasConfig(msg.elapsedDetik, msg.bebasStartDurasi,
                    msg.bebasInterval, msg.bebasDurasi)
                applyHdmiConfig(msg)
                if (msg.totalTagihan.isNotBlank()) {
                    lastTotal = msg.totalTagihan
                    if (msg.lunasTotal.isNotBlank()) lastLunas = msg.lunasTotal
                    if (msg.tagihanTotal.isNotBlank()) lastTagihan = msg.tagihanTotal
                    overlay?.updateBill(msg.totalTagihan, msg.lunasTotal, msg.tagihanTotal)
                }
                if (msg.isLastTime != isLastTime) {
                    // Server mengirim flag ini setiap detik saat Last Time;
                    // simpan agar popup tetap tampil walau mode overlay hidden.
                    isLastTime = msg.isLastTime
                }
                timer?.sync(msg.sisaDetik, msg.reconnect)
                if (msg.elapsedDetik >= 0) {
                    updateTimerUi(if (msg.isBebas) -1 else msg.sisaDetik)
                } else if (isLastTime) {
                    updateTimerUi(msg.sisaDetik)
                }
                if (msg.popupDetik > 0) tampilkanPopupEvent(msg.popupDetik)
                if (msg.sisaDetik >= 0 && !msg.noWake) setSessionScreenOn(true)
                simpanSesiLokal()
            }

            Actions.OVERLAY_STYLE -> {
                val st = Prefs.OverlayStyle(
                    alpha = if (msg.bgAlpha in 0..100) msg.bgAlpha else lastStyle?.alpha ?: Prefs.DEFAULT_ALPHA,
                    accent = msg.accent.ifBlank { lastStyle?.accent ?: Prefs.DEFAULT_ACCENT },
                    radius = if (msg.radius >= 0) msg.radius else lastStyle?.radius ?: Prefs.DEFAULT_RADIUS,
                    timerSize = if (msg.timerSize >= 0) msg.timerSize else lastStyle?.timerSize ?: Prefs.DEFAULT_TIMER_SIZE,
                    scale = if (msg.scale >= 0) msg.scale else lastStyle?.scale ?: Prefs.DEFAULT_SCALE,
                    posY = if (msg.posY >= 0) msg.posY else lastStyle?.posY ?: Prefs.DEFAULT_POS_Y,
                )
                lastStyle = st
                Prefs.saveOverlayStyle(this, st.alpha, st.accent, st.radius,
                    st.timerSize, st.scale, st.posY)
                overlay?.applyStyle(st)
                pinOverlay?.applyStyle(st)
                // Kartu yang sedang tampil ikut berubah seketika.
                if (overlay?.isShowing == true) overlay?.updateTimer(overlayTeks)
                if (pinOverlay?.isShowing == true) pinOverlay?.show(lastPin, lastMeja)
                laporkanKeKasir("tv_overlay_style", true,
                    "gaya popup alpha=${st.alpha}% warna=${st.accent} " +
                        "radius=${st.radius} timer=${st.timerSize} " +
                        "skala=${st.scale}% posY=${st.posY}dp")
            }

            Actions.LOCK_SCREEN -> {
                setSessionScreenOn(true)
                isLastTime = false
                timer?.stop()
                overlay?.hide()
                // Sesi berakhir terkunci — snapshot sesi tidak berlaku lagi.
                Prefs.clearSesiSnapshot(this)
                lastPromoUrl = msg.detail?.promoUrl ?: ""
                Prefs.savePromo(this, lastPromoUrl, lastPromoType)
                val d = msg.detail ?: LockDetail(msg.mejaId, "-", "Rp 0", "Rp 0")
                setLocked(true, d)
                laporkanKeKasir(
                    "tv_lockscreen", true,
                    "lockscreen tampil: meja=${d.meja} sewa=${d.sewa} " +
                            "fnb=${d.fnb} total=${d.total} lunas=${d.lunasTotal} " +
                            "tagihan=${d.tagihanTotal}")
            }

            Actions.UNLOCK_SCREEN -> {
                isLastTime = false
                setLocked(false, null)
                Prefs.clearSesiSnapshot(this)
                laporkanKeKasir("tv_unlock", true, "lockscreen ditutup atas perintah kasir")
            }

            Actions.UPDATE_LOGO -> {
                // Logo lock diganti kasir (tombol LOGO / Ganti Logo Lock):
                // refresh langsung lockscreen yang sedang tampil. v4.13: kasir
                // juga bisa ganti lewat adb push (local=logo.png) tanpa URL.
                if (locked && (msg.logoUrl.isNotBlank() || msg.local.isNotBlank())) {
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
                // Promo dari kasir diabaikan selama pairing supaya tidak menutupi
                // dialog kode pairing sistem.
                if (pairingMode) {
                    Log.d("RRTVService", "SHOW_MEDIA: skip (pairing mode)")
                    laporkanKeKasir("tv_promo", true,
                                    "promo ditunda — kasir sedang pairing TV")
                } else if (msg.mediaUrl.isNotBlank() || msg.local.isNotBlank()) {
                    // Arm promo untuk diputar 1x saat TV bangun dari tidur
                    // (media terakhir, video ATAU gambar — sampai media baru).
                    // v4.13: kasir mengirim `local` (nama file hasil adb push);
                    // URL hanya cadangan streaming.
                    lastPromoUrl = msg.mediaUrl
                    lastPromoType = msg.mediaType.ifBlank { "video" }
                    Prefs.savePromo(this, lastPromoUrl, lastPromoType)
                    // Promo yang sedang tampil = mulai ulang dari awal (klik
                    // "putar lagi"), bukan activity kedua yang menumpuk.
                    promoMulaiMs = SystemClock.elapsedRealtime()
                    val tampil = MediaActivity.instance
                    if (tampil != null) {
                        tampil.putarUlang(msg.mediaType, msg.mediaUrl, msg.local)
                    } else {
                        MediaActivity.start(this, msg.mediaType, msg.mediaUrl, msg.local)
                    }
                    updateNotification("Media: ${msg.mediaType}")
                    laporkanKeKasir("tv_promo", true,
                                    "promo ${msg.mediaType} diputar: " +
                                            (msg.local.ifBlank { msg.mediaUrl }))
                } else {
                    laporkanKeKasir("tv_promo", false, "SHOW_MEDIA tanpa URL/lokal")
                }
            }

            Actions.HIDE_MEDIA -> {
                // Jangan `finish()` telanjang: tanpa arahan balik ke input HDMI
                // TV akan mendarat di launcher Android. Promo yang tampil ditutup
                // lalu dikembalikan ke port terakhir.
                MediaActivity.tutupDanKembaliKeInput()
                laporkanKeKasir("tv_promo_sembunyi", true, "promo ditutup")
            }

            Actions.SHOW_MESSAGE -> {
                // Banner pesan singkat dari kasir (mis. "Mohon Jangan Ribut").
                // Non-intrusif: overlay atas transparan, hilang sendiri —
                // game/HDMI di belakangnya tetap jalan.
                val teks = msg.pesan.trim()
                when {
                    pairingMode -> laporkanKeKasir(
                        "tv_pesan", false, "pairing mode — pesan tidak ditampilkan")
                    teks.isEmpty() -> laporkanKeKasir(
                        "tv_pesan", false, "SHOW_MESSAGE tanpa teks")
                    !layarNyala() -> laporkanKeKasir(
                        "tv_pesan", false, "layar TV tidur — pesan tidak ditampilkan")
                    else -> {
                        messageOverlay?.show(teks, msg.durasi)
                        laporkanKeKasir(
                            "tv_pesan", true,
                            "pesan tampil ${msg.durasi.coerceIn(3, 300)} dtk: " +
                                    teks.take(60))
                    }
                }
            }

            Actions.SHOW_PIN -> {
                if (msg.pin.isNotBlank()) {
                    lastPin = msg.pin
                    pinOverlay?.show(msg.pin, msg.mejaId)
                    laporkanKeKasir("qr_pin_tampil", true, "PIN tampil di TV ${msg.mejaId}")
                } else {
                    laporkanKeKasir("qr_pin_tampil", false, "SHOW_PIN tanpa PIN")
                }
            }

            Actions.HIDE_PIN -> {
                pinOverlay?.hide()
                laporkanKeKasir("qr_pin_sembunyi", true,
                                "PIN disembunyikan (pemesan masuk sesi)")
            }

            Actions.SHOW_QR -> {
                // Kasir menekan 👤 MEMBER: QR di kiri ¼ layar, panel kanan berisi
                // video gambar bergerak + info rental. Sempre pastikan TV menyala.
                if (msg.mediaUrl.isNotBlank()) {
                    setSessionScreenOn(true)
                    val bg = msg.bgUrl.ifBlank { Prefs.lockBgUrl(this) }
                    qrOverlay?.show(msg.mediaUrl, msg.mejaId, msg.grup, lastRental, bg)
                    updateNotification("Menunggu scan QR member")
                    laporkanKeKasir("qr_member_tampil", true,
                                    "QR member tampil grup=${msg.grup}")
                } else {
                    laporkanKeKasir("qr_member_tampil", false, "SHOW_QR tanpa URL")
                }
            }

            Actions.HIDE_QR -> {
                qrOverlay?.hide()
                laporkanKeKasir("qr_member_sembunyi", true,
                                "QR member ditutup (sesi member mulai)")
            }

            Actions.UPDATE_LOCK_BG -> {
                // Kasir mengunggah gambar bergerak baru -> simpan untuk lockscreen
                // dan panel kanan layar QR. JANGAN menutup overlay QR yang sedang
                // tampil (hanya lockscreen yang perlu disegarkan). v4.13: update
                // juga bisa datang tanpa URL (hanya adb push local=lockscreen.mp4).
                if (msg.bgUrl.isNotBlank() || msg.local.isNotBlank()) {
                    if (msg.bgUrl.isNotBlank()) Prefs.saveLockBg(this, msg.bgUrl)
                    val sumber = msg.bgUrl.ifBlank { Prefs.lockBgUrl(this) }
                    LockScreenActivity.updateBgUrl(sumber)
                    qrOverlay?.updateBgVideo(sumber)
                }
            }

            Actions.OVERLAY_SETTINGS -> {
                applyOverlayConfig(msg.overlayMode, msg.overlayLastMinutes,
                    msg.bebasStartDurasi, msg.bebasInterval, msg.bebasDurasi)
                val t = timer
                updateTimerUi(if (t?.isBebas() == true) -1 else t?.remainingSeconds ?: 0)
                laporkanKeKasir("tv_overlay_setting", true,
                    "mode=$overlayMode menit=$overlayLastMinutes " +
                        "bebas_awal=$bebasStartDurasi interval=$bebasInterval durasi=$bebasDurasi")
            }

            Actions.SLEEP_TV -> {
                jadwalkanSleep(msg.countdown)
            }

            Actions.PICK_MEDIA -> {
                val tipe = msg.mediaType.ifBlank { msg.local }.ifBlank { "promo" }
                MediaPickerActivity.start(this, tipe)
            }

            Actions.DELETE_MEDIA -> {
                val nama = msg.local.ifBlank {
                    if (msg.mediaType == "lockscreen") "lockscreen.mp4" else "promo.mp4"
                }
                val f = Prefs.mediaFile(this, nama)
                f.delete()
                laporkanKeKasir("media_delete", true, "$nama dihapus")
            }

            Actions.QUERY_SCREEN_STATE -> {
                sendScreenState(layarNyala())
            }

            Actions.REPORT_LOGS -> {
                collectAndSendLogs(force = true)
            }

            Actions.RECONNECT_WS -> {
                ws?.forceReconnect()
                laporkanKeKasir("tv_ws_reconnect", true, "reconnect diminta RR Monitor")
                mainHandler.postDelayed({ collectAndSendLogs(force = true) }, 2_500L)
            }

            Actions.RESTART_CLIENT -> {
                laporkanKeKasir("tv_client_restart", true, "restart diminta RR Monitor")
                mainHandler.postDelayed({
                    stopSelf()
                    TvOverlayService.start(applicationContext)
                }, 800L)
            }

            Actions.PAIRING_MODE -> {
                // Hanya berlaku untuk TV dengan IP yang diminta kasir (TV yang
                // sedang di-pair). IP kosong = semua TV.
                val target = msg.targetIp.trim()
                if (target.isNotEmpty() && target != NetUtil.localIpv4(this)) return@dispatchServerMessage
                applyPairingMode(msg.pairing)
            }

            else -> Unit
        }
    }

    // ── Timer / overlay UI ───────────────────────────────────────────────────
    private fun applyPairingMode(on: Boolean) {
        if (pairingMode == on) return
        pairingMode = on
        if (on) {
            // Bereskan layar supaya dialog kode pairing sistem punya tempat:
            // tutup promo/PIN/QR yang sedang tampil dan jangan sentuh layar lagi.
            wakePromoArmed = false
            try { MediaActivity.finishInstance() } catch (_: Exception) {}
            pinOverlay?.hide()
            qrOverlay?.hide()
            messageOverlay?.hide()
            updateNotification("Pairing dari kasir — jangan matikan TV")
            Log.d("RRTVService", "PAIRING_MODE on: ${NetUtil.localIpv4(this)}")
        } else {
            updateNotification("Siap")
            Log.d("RRTVService", "PAIRING_MODE off: ${NetUtil.localIpv4(this)}")
        }
    }

    private fun normalizeOverlayMode(mode: String): String = when (mode.trim().lowercase()) {
        "hidden", "never", "off" -> "never"
        "last_minutes", "last" -> "last_minutes"
        else -> "always"
    }

    private fun applyOverlayConfig(mode: String, lastMinutes: Int,
                                   startDurasi: Int, interval: Int, durasi: Int) {
        val newMode = if (mode.isNotBlank()) normalizeOverlayMode(mode) else overlayMode
        val newLast = if (lastMinutes >= 1) lastMinutes.coerceIn(1, 120) else overlayLastMinutes
        val newStart = startDurasi.coerceIn(0, 120)
        val newInterval = interval.coerceIn(1, 1440)
        val newDurasi = durasi.coerceIn(1, 120)
        val changed = newMode != overlayMode || newLast != overlayLastMinutes ||
            newStart != bebasStartDurasi || newInterval != bebasInterval ||
            newDurasi != bebasDurasi
        overlayMode = newMode
        overlayLastMinutes = newLast
        bebasStartDurasi = newStart
        bebasInterval = newInterval
        bebasDurasi = newDurasi
        if (changed) {
            Prefs.saveOverlayConfig(this, overlayMode, overlayLastMinutes,
                bebasStartDurasi, bebasInterval, bebasDurasi)
        }
    }

    private fun applyBebasConfig(elapsed: Int, startDurasi: Int, interval: Int, durasi: Int) {
        if (elapsed >= 0) bebasElapsed = elapsed
        if (startDurasi >= 0) bebasStartDurasi = startDurasi.coerceIn(0, 120)
        if (interval >= 1) bebasInterval = interval.coerceIn(1, 1440)
        if (durasi >= 1) bebasDurasi = durasi.coerceIn(1, 120)
    }

    // ── Persistensi sesi & pemulihan offline (v4.14) ─────────────────────────

    /**
     * Simpan snapshot sesi berjalan ke Prefs (JSON). Dipanggil paksa pada
     * START/PAUSE/RESUME + saat TV tidur; terjadwal (maks 1x per 15 dtk) pada
     * SYNC/UPDATE_TOTAL yang datang tiap detik. State STOPPED = hapus snapshot.
     */
    private fun simpanSesiLokal(paksa: Boolean = false) {
        val t = timer ?: return
        val st = t.state
        if (st == TimerEngine.State.STOPPED) {
            Prefs.clearSesiSnapshot(this)
            return
        }
        val now = System.currentTimeMillis()
        if (!paksa && now - lastSesiSaveMs < 15_000L) return
        lastSesiSaveMs = now
        try {
            val o = JSONObject()
            o.put("paused", st == TimerEngine.State.PAUSED)
            o.put("bebas", st == TimerEngine.State.BEBAS)
            o.put("sisa", t.remainingSeconds)
            o.put("ts", now)
            o.put("meja", lastMeja)
            o.put("rental", lastRental)
            o.put("total", lastTotal)
            o.put("lunas", lastLunas)
            o.put("tagihan", lastTagihan)
            o.put("mode", overlayMode)
            o.put("mins", overlayLastMinutes)
            o.put("b_elapsed", bebasElapsed)
            o.put("b_start", bebasStartDurasi)
            o.put("b_interval", bebasInterval)
            o.put("b_durasi", bebasDurasi)
            Prefs.saveSesiSnapshot(this, o.toString())
            Log.d("RRTVService", "sesi disimpan: state=$st sisa=${t.remainingSeconds}s")
        } catch (_: Exception) {
        }
    }

    /**
     * Pulihkan snapshot sesi dari Prefs ke memori (tanpa menampilkan UI —
     * tampil lewat [tampilkanSesiPulih] saat layar benar-benar nyala).
     *
     * Snapshot yang sudah kedaluwarsa saat dipulihkan DIBUANG tanpa kunci:
     * kasus "TV lama mati / CLI lama offline" — menurut pemilik, promo tetap
     * diputar dan TV bebas dipakai (jangan kunci dengan data basi).
     */
    private fun pulihkanSesiLokal() {
        val raw = Prefs.sesiSnapshot(this)
        if (raw.isBlank()) return
        if (locked) {
            Prefs.clearSesiSnapshot(this)
            return
        }
        try {
            val o = JSONObject(raw)
            val bebas = o.optBoolean("bebas", false)
            val paused = o.optBoolean("paused", false)
            val sisa = o.optInt("sisa", 0)
            val ts = o.optLong("ts", 0L)
            lastMeja = o.optString("meja", lastMeja).ifBlank { lastMeja }
            lastRental = o.optString("rental", lastRental).ifBlank { lastRental }
            lastTotal = o.optString("total", lastTotal)
            lastLunas = o.optString("lunas", lastLunas)
            lastTagihan = o.optString("tagihan", lastTagihan)
            overlayMode = o.optString("mode", overlayMode).ifBlank { overlayMode }
            overlayLastMinutes = o.optInt("mins", overlayLastMinutes)
            bebasElapsed = o.optInt("b_elapsed", bebasElapsed)
            bebasStartDurasi = o.optInt("b_start", bebasStartDurasi)
            bebasInterval = o.optInt("b_interval", bebasInterval)
            bebasDurasi = o.optInt("b_durasi", bebasDurasi)
            if (bebas) {
                sesiPulihBebas = true
                sesiPulihPaused = false
                sesiPulihRemain = -1
                Log.i("RRTVService", "snapshot Main Bebas dipulihkan")
                return
            }
            var remain = sisa
            if (!paused && ts > 0L) {
                remain -= ((System.currentTimeMillis() - ts) / 1000L).toInt()
            }
            if (remain <= 0) {
                Log.i("RRTVService",
                    "snapshot sesi sudah kedaluwarsa ($remain dtk) — dibuang, TIDAK dikunci")
                Prefs.clearSesiSnapshot(this)
                return
            }
            sesiPulihRemain = remain
            sesiPulihPaused = paused
            sesiPulihBebas = false
            Log.i("RRTVService", "snapshot sesi dipulihkan: sisa=${remain}s paused=$paused")
        } catch (_: Exception) {
            Prefs.clearSesiSnapshot(this)
        }
    }

    /** Tampilkan overlay + jalankan countdown dari snapshot yang dipulihkan. */
    private fun tampilkanSesiPulih() {
        val t = timer ?: return
        if (sesiPulihRemain <= 0 && !sesiPulihBebas) return
        val bebas = sesiPulihBebas
        val remain = sesiPulihRemain
        val paused = sesiPulihPaused
        sesiPulihRemain = -1
        sesiPulihBebas = false
        setSessionScreenOn(true)
        overlay?.show(lastMeja, lastRental, lastTotal, lastLunas, lastTagihan)
        if (bebas) {
            t.start(-1, true)
            mulaiBebasTicker()
            updateTimerUi(-1)
            Log.i("RRTVService", "popup Main Bebas dipulihkan lokal (CLI offline)")
        } else {
            t.start(remain, true)
            if (paused) t.pause()
            updateNotification("${lastMeja} — ${OverlayWidget.formatHms(remain)}")
            Log.i("RRTVService", "popup waktu dipulihkan lokal (CLI offline): sisa=${remain}s")
        }
        laporkanKeKasir("tv_overlay_timer", true,
            "popup waktu dipulihkan lokal (offline) sisa=${if (bebas) "∞" else "${remain}s"}")
    }

    /**
     * Dipanggil setiap TV selesai bangun (SCREEN_ON / cold boot): kalau ada
     * snapshot menunggu, tampilkan; kalau timer masih hidup di memori
     * (proses tidak mati), cukup pastikan overlay & teksnya segar.
     */
    private fun refreshOverlayPascaBangun() {
        if (locked || pairingMode || !layarNyala()) return
        if (sesiPulihRemain > 0 || sesiPulihBebas) {
            tampilkanSesiPulih()
            return
        }
        val t = timer ?: return
        when (t.state) {
            TimerEngine.State.RUNNING, TimerEngine.State.PAUSED ->
                updateTimerUi(t.remainingSeconds)
            TimerEngine.State.BEBAS -> {
                mulaiBebasTicker()
                updateTimerUi(-1)
            }
            else -> Unit
        }
    }

    /** Main Bebas offline: tambah detik berjalan lokal (online dari server). */
    private fun mulaiBebasTicker() {
        if (bebasTicker != null) return
        val r = object : Runnable {
            override fun run() {
                if (timer?.isBebas() != true) {
                    bebasTicker = null
                    return
                }
                if (ws?.connected != true) {
                    bebasElapsed += 1
                    if (layarNyala()) updateTimerUi(-1)
                    // Simpan berkala supaya restart app tidak kehilangan detik.
                    if (bebasElapsed % 30 == 0) simpanSesiLokal(paksa = true)
                }
                mainHandler.postDelayed(this, 1000L)
            }
        }
        bebasTicker = r
        mainHandler.postDelayed(r, 1000L)
    }

    /**
     * CLI offline saat bangun & TV masih terkunci dari status LAMA: buka kunci
     * lokal (keputusan pemilik). Saat CLI hidup, snapshot server yang berlaku —
     * fungsi ini tidak pernah dipanggil.
     */
    private fun bukaKunciOffline() {
        if (!offlineUnlockPending) return
        offlineUnlockPending = false
        cancelLockFallback()
        Log.i("RRTVService", "CLI offline: buka kunci lokal (TV bebas dipakai)")
        setLocked(false, null)
        laporkanKeKasir("tv_unlock", true,
            "lockscreen dibuka lokal — CLI offline saat TV bangun")
    }

    // ── Port HDMI pilihan kasir per TV (v4.13) ───────────────────────────────
    // Kasir mengirim `hdmi_port` + `hdmi_input_hint` di START_TIMER/SYNC_TIMER:
    //   1..4 = app pindah ke port itu setelah promo; 0 = belum diisi (jangan
    //   sentuh input); -1 = "Jangan pakai" (TV atur sendiri). Field TIDAK
    //   dikirim (kasir lama) = Int.MIN_VALUE -> Prefs tidak diubah.
    // Laporan ke kasir HANYA saat nilai berubah — SYNC_TIMER datang tiap detik,
    // tanpa penjagaan ini kartu TV akan dibanjiri event.
    private var lastHdmiLog = ""

    private fun applyHdmiConfig(msg: ServerMessage) {
        if (msg.hdmiPort == Int.MIN_VALUE) return
        val hintBaru = msg.hdmiInputHint.trim()
        val hintLama = Prefs.hdmiInputHint(this)
        if (msg.hdmiPort == Prefs.hdmiPort(this) && hintBaru == hintLama) return
        Prefs.saveHdmi(this, msg.hdmiPort,
            if (msg.hdmiInputHint.isNotBlank()) hintBaru else null)
        val label = when (msg.hdmiPort) {
            -1 -> "Jangan pakai (TV atur sendiri)"
            0 -> "belum diisi (app tidak menyentuh input)"
            else -> "HDMI${msg.hdmiPort}" + if (hintBaru.isNotBlank()) " [$hintBaru]" else ""
        }
        val kunci = "${msg.hdmiPort}|$hintBaru"
        Log.i("RRTVService", "konfigurasi HDMI baru: $label")
        if (kunci != lastHdmiLog) {
            lastHdmiLog = kunci
            laporkanKeKasir("tv_hdmi_config", true, "port input: $label")
        }
    }

    private var bebasElapsed = 0
    private var bebasStartDurasi = 5
    private var bebasInterval = 60
    private var bebasDurasi = 10
    private var lastPin = ""
    private var lastStyle: Prefs.OverlayStyle? = null
    private var overlayTeks = "00:00:00"

    /**
     * True bila Main Bebas sedang berada di dalam jendela tampil popup.
     * Menit ke-0, ke-60, ke-120, ... masing-masing tampil selama durasi detik.
     */
    private fun bebasPopupJendela(): Boolean {
        if (bebasStartDurasi > 0 && bebasElapsed < bebasStartDurasi) return true
        if (bebasInterval < 1 || bebasDurasi < 1) return true
        val menit = bebasElapsed / 60
        val detik = bebasElapsed % 60
        return (menit % bebasInterval == 0) && (detik < bebasDurasi)
    }

    private fun eventPopupAktif(): Boolean =
        SystemClock.elapsedRealtime() < eventPopupUntilMs

    private fun updateTimerUi(remaining: Int) {
        val bebas = timer?.isBebas() == true
        val popupEvent = eventPopupAktif()
        if (bebas) {
            // Main Bebas: popup TIDAK menempel terus — hanya sebentar secara
            // berkala (mis. 30 detik tiap 60 menit) supaya tidak menutupi game.
            // Isinya waktu berjalan + total, bukan sekadar "∞ BEBAS" yang tidak
            // membantu pelanggan tahu sudah berapa lama dia main.
            if (!popupEvent && !bebasPopupJendela()) {
                overlay?.hide()
                return
            }
            ensureOverlayVisible()
            overlayTeks = OverlayWidget.formatHms(bebasElapsed)
            overlay?.updateTimer(overlayTeks)
            overlay?.updateMejaDanTotal(
                meja = "${lastMeja} · ∞ BEBAS",
                total = buildTotalBermain(),
                lunas = "",
                tagihan = "",
            )
        } else {
            // Last Time wajib tampil walau kasir memilih mode "hidden": ini
            // justru satu-satunya penanda sisa waktu tambahan untuk pelanggan.
            val visible = isLastTime || popupEvent || when (overlayMode) {
                "never", "hidden" -> false
                "last_minutes" -> remaining >= 0 && remaining <= overlayLastMinutes * 60
                else -> true
            }
            if (visible) {
                ensureOverlayVisible()
                overlayTeks = OverlayWidget.formatHms(remaining)
                overlay?.updateTimer(overlayTeks)
            } else {
                overlay?.hide()
            }
        }
        if (remaining <= 0 && !bebas) updateNotification("Waktu habis")
    }

    /** Baris total khusus Main Bebas: "Rp 45.000 BERJALAN". */
    private fun buildTotalBermain(): String {
        val angka = lastTotal.removePrefix("Rp").trim()
        return if (angka.isEmpty() || angka == "0") "" else "Rp $angka BERJALAN"
    }

    private fun ensureOverlayVisible() {
        val o = overlay ?: return
        if (!o.isShowing) o.show(lastMeja, lastRental, lastTotal, lastLunas, lastTagihan)
    }

    private fun cancelScheduledSleep() {
        sleepRunnable?.let { mainHandler.removeCallbacks(it) }
        sleepRunnable = null
    }

    private fun jadwalkanSleep(countdownDetik: Int) {
        cancelScheduledSleep()
        val detik = countdownDetik.coerceIn(0, 300)
        if (detik <= 0) {
            lakukanSleep("segera")
            return
        }
        val r = Runnable { lakukanSleep("countdown ${detik}s") }
        sleepRunnable = r
        mainHandler.postDelayed(r, detik * 1000L)
        laporkanKeKasir("tv_sleep_jadwal", true, "TV tidur dalam ${detik} detik")
    }

    private fun lakukanSleep(alasan: String) {
        sleepRunnable = null
        eventPopupRunnable?.let { mainHandler.removeCallbacks(it) }
        eventPopupRunnable = null
        eventPopupUntilMs = 0L
        laporkanKeKasir("tv_sleep", true, "TV tidur ($alasan)")
        setLocked(false, null)
        timer?.stop()
        overlay?.hide()
        qrOverlay?.hide()
        pinOverlay?.hide()
        messageOverlay?.hide()
        Prefs.clearSesiSnapshot(this)
        setSessionScreenOn(false)
        try { MediaActivity.finishInstance() } catch (_: Exception) {}
        mainHandler.postDelayed({
            try {
                val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
                val admin = ComponentName(this, KioskAdminReceiver::class.java)
                if (dpm.isAdminActive(admin) || dpm.isDeviceOwnerApp(packageName)) {
                    dpm.lockNow()
                }
            } catch (e: Exception) {
                Log.w("RRTVService", "sleep fallback gagal: ${e.message}")
            }
        }, 700L)
    }

    private fun tampilkanPopupEvent(detik: Int) {
        val durasi = detik.coerceIn(1, 30)
        eventPopupUntilMs = SystemClock.elapsedRealtime() + durasi * 1000L
        eventPopupRunnable?.let { mainHandler.removeCallbacks(it) }
        val t = timer
        updateTimerUi(if (t?.isBebas() == true) -1 else t?.remainingSeconds ?: 0)
        val r = Runnable {
            if (SystemClock.elapsedRealtime() >= eventPopupUntilMs) {
                eventPopupUntilMs = 0L
                val cur = timer
                updateTimerUi(if (cur?.isBebas() == true) -1 else cur?.remainingSeconds ?: 0)
            }
        }
        eventPopupRunnable = r
        mainHandler.postDelayed(r, durasi * 1000L + 80L)
    }

    private fun autoLock() {
        Log.d("RRTVService", "timer selesai -> autoLock")
        overlay?.hide()
        // Sesi tamat: snapshot tidak boleh dipulihkan lagi (kalau tidak,
        // popup bangkit kembali setelah TV tidur-nyala).
        Prefs.clearSesiSnapshot(this)
        // Pakai detail dari server bila ada; kalau belum sempat tiba, pakai
        // total terakhir yang diketahui supaya tidak tampil "Rp 0".
        val detail = lockDetail ?: LockDetail(
            lastMeja, "-", "Rp 0", lastTotal,
            lunasTotal = lastLunas, tagihanTotal = lastTagihan)
        setLocked(true, detail)
        laporkanKeKasir(
            "tv_waktu_habis", true,
            "waktu habis di TV, lockscreen tampil otomatis: total=${detail.total} " +
                    "lunas=${detail.lunasTotal} tagihan=${detail.tagihanTotal}")
    }

    private fun setLocked(value: Boolean, detail: LockDetail?) {
        Log.d("RRTVService", "setLocked(value=$value, detail=${detail?.meja}) wasLocked=$locked")
        if (locked == value && lockDetail == detail) {
            Log.d("RRTVService", "setLocked: early return (no change)")
            return
        }
        val wasLocked = locked
        locked = value
        lockDetail = detail
        if (value) {
            Prefs.saveLock(this, detail)
            if (pairingMode) {
                // Jangan buka lockscreen saat kasir sedang pairing — activity
                // ini akan menutupi dialog kode pairing sistem.
                Log.d("RRTVService", "setLocked: skip lockscreen (pairing mode)")
            } else if (wasLocked) {
                // Lockscreen sudah tampil (mis. autoLock saat countdown habis):
                // jangan buka activity baru — cukup perbarui isinya dengan
                // detail terbaru dari server (total valid saat waktu habis).
                LockScreenActivity.updateDetail(detail)
            } else {
                LockScreenActivity.start(this, detail)
            }
        } else {
            Prefs.clearLock(this)
            LockScreenActivity.finishInstance()
        }
        notifyLock(value)
        // Kabari kasir status layar ikut berubah (lockscreen on/off).
        reportStatusKeKasir()
    }

    /**
     * Kirim status TV (hidup/mati + input + mode layar) ke server kasir.
     * Dipanggil berkala & setiap kali tampilan berubah supaya kartu TV di
     * kasir selalu mencerminkan kondisi nyata TV.
     */
    private fun reportStatusKeKasir() {
        mainHandler.postDelayed({
            sendScreenState(layarNyala())
        }, 800)
    }

    /**
     * Kabari server kasir kejadian penting client (sukses/gagal) supaya
     * masuk Log Aplikasi kasir tanpa perlu baca logcat manual.
     */
    private fun laporkanKeKasir(aksi: String, ok: Boolean, pesan: String) {
        val w = ws ?: return
        try {
            val json = JSONObject()
                .put("type", "CLIENT_EVENT")
                .put("meja_id", lastMeja)
                .put("event", aksi)
                .put("ok", ok)
                .put("message", pesan.take(200))
            w.sendRaw(json.toString())
            if (ok) Log.d("RRTVService", "OK [$aksi]: $pesan")
            else Log.w("RRTVService", "GAGAL [$aksi]: $pesan")
        } catch (_: Exception) {
        }
    }

    private var _izinTerakhirDikirim: String = ""

    /**
     * Kirim laporan kelengkapan izin ke kasir — hanya bila status berubah.
     * Dipanggil dari service saat WebSocket tersambung supaya laporan tetap
     * terkujo anche setelah TV bangun / aplikasi client di-restart.
     */
    fun laporkanIzanKeKasirSafe() {
        val items = try {
            com.rrbillingpro.tvclient.permission.PermissionKit.periksaSemua(this)
        } catch (_: Exception) {
            return
        }
        val sidik = items.joinToString(",") { "${it.key}=${if (it.ok) "1" else "0"}" }
        if (sidik == _izinTerakhirDikirim) return
        // Cache baru disimpan setelah benar-benar terkirim — kalau WebSocket
        // belum siap, laporan akan dicoba lagi pada kesempatan berikutnya.
        if (laporkanIzinKeKasir(items)) {
            _izinTerakhirDikirim = sidik
        }
    }

    /** Alias yang dipakai MainActivity (nama ringkas). */
    fun laporkanIzinKeKasir() = laporkanIzanKeKasirSafe()

    /**
     * Kabari server kasir kelengkapan izin client (overlay, device owner,
     * battery, background, developer options, dst). Kasir menampilkan ini di
     * kartu TV dan memberi panduan perbaikan bila ada yang belum aktif.
     *
     * Return true bila benar-benar terkirim ke server.
     */
    fun laporkanIzinKeKasir(items: List<com.rrbillingpro.tvclient.permission.PermissionKit.Item>): Boolean {
        val w = ws ?: return false
        if (!w.connected) return false
        return try {
            val rincian = items.joinToString(", ") {
                "${it.key}=${if (it.ok) "OK" else "BELUM"}"
            }
            val belum = items.count { !it.ok }
            val json = JSONObject()
                .put("type", "CLIENT_EVENT")
                .put("meja_id", lastMeja)
                .put("event", "tv_izin_client")
                .put("ok", belum == 0)
                .put("message", rincian)
            w.sendRaw(json.toString())
            Log.i("RRTVService", "Izin client dilaporkan: $rincian")
            true
        } catch (_: Exception) {
            false
        }
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
            lastWsConnectedMs = System.currentTimeMillis()
            // Saat (re)connect: kirim status layar terkini supaya server langsung
            // tahu TV hidup/mati + port input yang dipakai tanpa menunggu
            // broadcast berikutnya.
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            sendScreenState(pm.isInteractive)
            // Laporkan kelengkapan izin juga saat tersambung — kasir butuh
            // tahuizin TV sudah lengkap atau belum.
            mainHandler.postDelayed({ laporkanIzinKeKasir() }, 1200)
        } else {
            lastWsDisconnectedMs = System.currentTimeMillis()
        }
        val copy = listeners.toList()
        for (l in copy) l.onStatusChanged(value)
    }

    companion object {
        @Volatile
        var instance: TvOverlayService? = null
            private set

        /** Jendela pembendung SCREEN_ON ganda pasca-boot: SCREEN_ON yang tiba
         *  dalam rentang ini setelah promo mulai dianggap event ganda. */
        private const val PROMO_DEDUP_MS = 10_000L

        /** Dipanggil MediaActivity saat selesai/failed: kabari kasir mode layar. */
        fun onPromoSelesai() {
            val svc = instance ?: return
            svc.reportStatusKeKasir()
            // v4.14: bangun-terkunci saat CLI offline = promo dulu, baru buka
            // kunci. Promo selesai / gagal tampil → kunci dibuka sekarang.
            // (Kalau MediaActivity tidak pernah jalan, timer 1,5 dtk di
            // SCREEN_ON yang membukanya.)
            if (svc.offlineUnlockPending && svc.ws?.connected != true) {
                svc.bukaKunciOffline()
            }
        }

        /** Promo selesai & TV sudah dikembalikan ke port HDMI tertentu. */
        fun laporkanPromoSelesai(inputId: String) {
            instance?.laporkanKeKasir(
                "tv_promo_selesai", true,
                "promo selesai, TV kembali ke input $inputId")
        }

        /**
         * Semua kandidat id input sudah dicoba tanpa berhasil — TV kemungkinan
         * mendarat di launcher Android. Kasir perlu tahu supaya bisa mengatur
         * input TV atau mengirim ulang perintah lewat ADB.
         */
        fun laporkanPromoGagalPindahInput(idDicoba: List<String>) {
            val daftar = idDicoba.joinToString().ifBlank {
                "(STB tidak punya id port HDMI yang bisa dibaca)"
            }
            instance?.laporkanKeKasir(
                "tv_promo_gagal_pindah_input", false,
                "TV tidak kembali ke port HDMI — dikembalikan ke Home Android. " +
                    "id input yang dicoba: $daftar")
        }

        /**
         * v4.15: promo selesai tanpa target HDMI yang pasti — TV diarahkan ke
         * launcher/Home Android asli (bukan lockscreen RRBilling).
         */
        fun laporkanPromoKeHome(berhasil: Boolean) {
            instance?.laporkanKeKasir(
                "tv_promo_ke_home", berhasil,
                if (berhasil) "pindah input dilewati — TV dikembalikan ke Home Android"
                else "pindah input dilewati — gagal membuka Home Android")
        }

        /**
         * Passthrough "berhasil" secara teknis tapi TV mendarat di port lain —
         * biasanya port yang tidak ada cabangnya, jadi pelanggan melihat
         * layar hitam. Kasir perlu tahu port tujuan dan port yang sebenarnya
         * supaya bisa mengarahkan TV ke port yang benar.
         */
        fun laporkanPromoSalahPort(sasaran: String, aktual: String) {
            instance?.laporkanKeKasir(
                "tv_promo_salah_port", false,
                "TV pindah ke port yang salah. diminta=$sasaran sebenarnya=$aktual " +
                    "— port tujuan mungkin tidak ada cabangnya (layar hitam)")
        }

        /**
         * v4.13 (anti-flash): selang waktu dari kasir/service meminta promo
         * sampai frame pertama benar-benar tampil di layar, dalam milidetik.
         * Dipakai kartu TV untuk memantau "app terbuka sekilas 1 detik".
         */
        fun laporkanLatensiPromo(ms: Long) {
            instance?.laporkanKeKasir(
                "tv_promo_latency", true,
                "promo tampil dalam ${ms}ms sejak perintah")
        }

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
