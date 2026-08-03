package com.rrbillingpro.tvclient.net

import android.os.Handler
import android.os.Looper
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.max

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

    fun start(totalSeconds: Int) {
        counter.incrementAndGet()
        remainingSeconds = max(0, totalSeconds)
        state = if (totalSeconds < 0) State.BEBAS else State.RUNNING
        onTick(remainingSeconds)
        if (state == State.RUNNING) scheduleTick()
    }

    fun pause() {
        counter.incrementAndGet()
        if (state == State.RUNNING) state = State.PAUSED
    }

    fun resume(totalSeconds: Int) {
        counter.incrementAndGet()
        if (state == State.PAUSED || state == State.RUNNING) {
            if (totalSeconds > 0) remainingSeconds = totalSeconds
            state = State.RUNNING
            scheduleTick()
        }
    }

    fun stop() {
        counter.incrementAndGet()
        state = State.STOPPED
        remainingSeconds = 0
    }

    /**
     * Sinkronisasi dari kasir: set ulang sisa waktu tanpa mengganggu state,
     * counter, atau jadwal tick (anti-drift saat sesi berjalan).
     */
    fun sync(totalSeconds: Int) {
        if (state == State.RUNNING && totalSeconds >= 0) {
            remainingSeconds = max(0, totalSeconds)
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
                    state = State.STOPPED
                    onFinished()
                } else {
                    scheduleTick()
                }
            }
        }, 1000L)
    }
}
