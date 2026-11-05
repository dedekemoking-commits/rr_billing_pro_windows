package com.rrbillingpro.tvclient.net

import android.os.Handler
import android.os.Looper
import android.util.Log
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.max

private const val TAG = "RRTimer"

/**
 * Toleransi drift sinkronisasi (detik).
 *
 * SYNC_TIMER dikirim kasir tiap detik; oskasir dan jam TV bisa berbeda
 * sedetik-sekikit, jadi nilai yang naik/turun 1-2 detik dianggap noise.
 * Selisih LEBIH dari ini = perubahan nyata, termasuk penambahan paket sesi.
 */
private const val SYNC_TOLERANCE = 2

/**
 * Jeda tunggu konfirmasi SYNC_TIMER 0 dari server setelah countdown lokal
 * menyentuh 0. Online, konfirmasi tiba dalam ~1 detik. Saat CLI putus
 * (offline), tidak akan pernah tiba — setelah jeda ini TV mengunci sendiri
 * (keputusan pemilik: "lanjut hitung mundur, kunci saat habis").
 */
private const val ZERO_GRACE_MS = 20_000L

/**
 * Mesin countdown sederhana (berjalan di main thread via Handler).
 *
 * State:
 *  - RUNNING : menghitung mundur tiap detik
 *  - PAUSED  : berhenti sementara (dari kasir)
 *  - BEBAS   : "Main Bebas" (tanpa batas waktu, sisaDetik = -1)
 *  - STOPPED : tidak ada sesi
 */
class TimerEngine(
    private val onTick: (remainingSeconds: Int) -> Unit,
    private val onFinished: () -> Unit,
) {
    enum class State { STOPPED, RUNNING, PAUSED, BEBAS }

    @Volatile var state: State = State.STOPPED
        private set

    @Volatile var remainingSeconds: Int = 0
        private set

    private val handler = Handler(Looper.getMainLooper())
    private val counter = AtomicInteger(0)
    private var lastSyncRemaining = -1
    private var waitingForServerZero = false

    /**
     * Mulai sesi baru / set ulang total waktu.
     *
     * `start()` bersifat AUTHORITATIF: nilai dari server kasir selalu diterima,
     * bahkan saat timer sedang berjalan dan nilainya lebih besar dari sisa
     * lokal. Sebelumnya nilai yang lebih besar diabaikan ("anti-drift") —
     * Akibatnya kasir yang memulai sesi baru tanpa STOP_TIMER lebih dulu
     * (mis. lanjut dari PIN/QR member, atau pindah sesi antar kartu) tidak
     * pernah me-reset timer, sehingga TV menampilkan sisa waktu & total sesi
     * LAMA ke pelanggan.
     *
     * Anti-drift tetap ditangani oleh [sync] (yang mengabaikan nilai yang
     * tertinggal), bukan di sini.
     */
    fun start(totalSeconds: Int, forceStart: Boolean = false) {
        counter.incrementAndGet()
        lastSyncRemaining = -1
        waitingForServerZero = false
        remainingSeconds = max(0, totalSeconds)
        state = if (totalSeconds < 0) State.BEBAS else if (totalSeconds == 0) State.STOPPED else State.RUNNING
        Log.d(TAG, "start total=${totalSeconds}s state=$state remaining=${remainingSeconds}s")
        onTick(remainingSeconds)
        if (state == State.RUNNING) scheduleTick()
        if (state == State.STOPPED && totalSeconds == 0) onFinished()
    }

    fun pause() {
        counter.incrementAndGet()
        if (state == State.RUNNING) state = State.PAUSED
    }

    fun resume(totalSeconds: Int) {
        counter.incrementAndGet()
        lastSyncRemaining = -1
        waitingForServerZero = false
        if (state == State.PAUSED || state == State.RUNNING) {
            if (totalSeconds >= 0) remainingSeconds = totalSeconds
            state = if (totalSeconds == 0) State.STOPPED else State.RUNNING
            Log.d(TAG, "resume total=${totalSeconds}s state=$state")
            onTick(remainingSeconds)
            if (state == State.RUNNING) scheduleTick()
            else if (totalSeconds == 0) onFinished()
        }
    }

    fun stop() {
        counter.incrementAndGet()
        waitingForServerZero = false
        state = State.STOPPED
        remainingSeconds = 0
    }

    /**
     * Sinkronisasi dari kasir: set ulang sisa waktu tanpa mengganggu state,
     * counter, atau jadwal tick (anti-drift saat sesi berjalan).
     *
     * Kasir mengirim SYNC_TIMER tiap detik. Nilai normal TURUN 1 detik tiap
     * detik — itulah yang dicek anti-drift di bawah.
     *
     * Nilai yang NAIK berarti kasir menambah paket sesi (mis. sisa 10 menit
     * + paket 1 jam = 70 menit). Itu perubahan sah dan WAJIB diterapkan,
     * tapi dengan toleransi kecil agar noise clock tidak membuat timer
     * meloncat. Tanpa penanganan ini, overlay TV menampilkan sisa waktu LAMA
     * sementara total tagihan sudah yang baru — pelanggan melihat "~10 menit"
     * padahal sudah membayar 1 jam tambahan.
     */
    fun sync(totalSeconds: Int, startIfStopped: Boolean = false) {
        if (totalSeconds < 0) return
        if (startIfStopped) lastSyncRemaining = -1
        if (state == State.STOPPED) {
            if (startIfStopped) {
                Log.d(TAG, "sync reconnect memulai timer total=${totalSeconds}s")
                start(totalSeconds, true)
            }
            return
        }
        if (state != State.RUNNING) return

        val reference = if (lastSyncRemaining >= 0) lastSyncRemaining else remainingSeconds
        val delta = totalSeconds - reference
        if (lastSyncRemaining >= 0 && delta in -SYNC_TOLERANCE..SYNC_TOLERANCE) {
            Log.d(TAG, "sync stale diabaikan incoming=${totalSeconds}s last=${lastSyncRemaining}s")
            return
        }

        val previous = remainingSeconds
        val wasWaiting = waitingForServerZero
        val paketDitambah = delta > SYNC_TOLERANCE
        remainingSeconds = totalSeconds
        lastSyncRemaining = totalSeconds
        waitingForServerZero = false
        if (paketDitambah) {
            Log.d(TAG, "sync paket ditambahkan: ${previous}s -> ${totalSeconds}s (+$delta s)")
        } else {
            Log.d(TAG, "sync authoritative incoming=${totalSeconds}s previous=${previous}s")
        }
        onTick(remainingSeconds)
        if (remainingSeconds == 0) {
            state = State.STOPPED
            onFinished()
        } else if (wasWaiting) {
            scheduleTick()
        }
    }

    fun isBebas(): Boolean = state == State.BEBAS

    private fun scheduleTick() {
        val token = counter.get()
        handler.postDelayed({
            if (token != counter.get()) return@postDelayed
            if (state != State.RUNNING) return@postDelayed

            if (remainingSeconds > 0) {
                remainingSeconds -= 1
                onTick(remainingSeconds)
                if (remainingSeconds <= 0) {
                    waitingForServerZero = true
                    Log.d(TAG, "timer lokal 0; menunggu SYNC_TIMER 0 dari server " +
                            "(grace ${ZERO_GRACE_MS / 1000}s)")
                    // Fallback offline: server mungkin tidak pernah menjawab
                    // (CLI putus). Tanpa ini, TV nyangkut di 0 selamanya dan
                    // pelanggan bisa main tanpa kunci.
                    val graceToken = counter.get()
                    handler.postDelayed({
                        if (graceToken != counter.get()) return@postDelayed
                        if (state == State.RUNNING && remainingSeconds <= 0) {
                            Log.d(TAG, "server tidak mengonfirmasi 0 — kunci lokal")
                            state = State.STOPPED
                            onFinished()
                        }
                    }, ZERO_GRACE_MS)
                } else {
                    scheduleTick()
                }
            }
        }, 1000L)
    }
}
