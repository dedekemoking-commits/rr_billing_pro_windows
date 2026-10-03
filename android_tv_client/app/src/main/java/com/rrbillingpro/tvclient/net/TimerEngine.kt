package com.rrbillingpro.tvclient.net

import android.os.Handler
import android.os.Looper
import android.util.Log
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.max

private const val TAG = "RRTimer"

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

    fun start(totalSeconds: Int, forceStart: Boolean = false) {
        if (!forceStart && state == State.RUNNING && totalSeconds >= 0 && totalSeconds > remainingSeconds) {
            Log.d(TAG, "start diabaikan: incoming=${totalSeconds}s current=${remainingSeconds}s")
            scheduleTick()
            return
        }
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
        if (lastSyncRemaining >= 0 && totalSeconds >= lastSyncRemaining) {
            Log.d(TAG, "sync stale diabaikan incoming=${totalSeconds}s last=${lastSyncRemaining}s")
            return
        }
        val previous = remainingSeconds
        val wasWaiting = waitingForServerZero
        remainingSeconds = totalSeconds
        lastSyncRemaining = totalSeconds
        waitingForServerZero = false
        Log.d(TAG, "sync authoritative incoming=${totalSeconds}s previous=${previous}s")
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
                    Log.d(TAG, "timer lokal 0; menunggu SYNC_TIMER 0 dari server")
                } else {
                    scheduleTick()
                }
            }
        }, 1000L)
    }
}
