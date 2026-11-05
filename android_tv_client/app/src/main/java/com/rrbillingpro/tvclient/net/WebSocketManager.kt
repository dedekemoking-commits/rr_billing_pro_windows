package com.rrbillingpro.tvclient.net

import android.content.Context
import android.os.Handler
import android.os.Looper
import com.rrbillingpro.tvclient.model.Actions
import com.rrbillingpro.tvclient.model.ServerMessage
import com.rrbillingpro.tvclient.util.NetUtil
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Manajer WebSocket berbasis OkHttp:
 *  - Auto-reconnect dengan exponential backoff (2s -> 4s -> 8s -> 10s, cap 10s)
 *  - Registrasi meja_id otomatis setelah konek
 *  - Balas PONG untuk pesan PING aplikasi (server kasir heartbeat 5 detik)
 */
class WebSocketManager(
    private val host: String,
    private val port: Int,
    private val mejaId: String,
    private val appContext: Context,
    private val onMessage: (ServerMessage) -> Unit,
    private val onStatusChanged: (Boolean) -> Unit,
) {
    private val client = OkHttpClient.Builder()
        .pingInterval(15, TimeUnit.SECONDS)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private val mainHandler = Handler(Looper.getMainLooper())
    private val reconnectHandler = Handler(Looper.getMainLooper())

    private var webSocket: WebSocket? = null
    private var attempt = 0
    private var closedByUser = false

    @Volatile var connected: Boolean = false
        private set

    fun start() {
        closedByUser = false
        connect()
    }

    /** Kirim pesan JSON bebas ke server kasir (mis. SCREEN_STATE). */
    fun sendRaw(json: String) {
        try {
            webSocket?.send(json)
        } catch (_: Exception) {
        }
    }

    /** Paksa putus & sambung ulang socket. Koneksi baru memicu REGISTER
     *  sehingga server mengirim ulang snapshot state (START/STOP/LOCK). */
    fun forceReconnect() {
        if (closedByUser) return
        val socket = webSocket
        webSocket = null
        try { socket?.close(1000, "resync") } catch (_: Exception) {}
        setConnected(false)
        attempt = 0
        reconnectHandler.removeCallbacksAndMessages(null)
        connect()
    }

    fun stop() {
        closedByUser = true
        reconnectHandler.removeCallbacksAndMessages(null)
        val socket = webSocket
        webSocket = null
        try {
            socket?.close(1000, "bye")
        } catch (_: Exception) {
        }
        setConnected(false)
    }

    private fun connect() {
        if (closedByUser || webSocket != null) return
        // Belum dipasangkan dengan kasir (URL server kosong): jangan crash dan
        // jangan loop reconnect — service tetap hidup & promo lokal tetap
        // berjalan. Manager baru dibuat setelah pairing mengisi URL.
        if (host.isBlank() || port <= 0) {
            android.util.Log.w("RRTVService",
                "URL server kosong — WebSocket tidak dijalankan (belum pairing)")
            return
        }
        val url = "ws://$host:$port"
        val request = Request.Builder().url(url).build()
        try {
            webSocket = client.newWebSocket(request, listener)
        } catch (_: Exception) {
            scheduleReconnect()
        }
    }

    private val listener = object : WebSocketListener() {
        override fun onOpen(ws: WebSocket, response: Response) {
            if (closedByUser || ws !== webSocket) {
                try { ws.close(1000, "stale") } catch (_: Exception) {}
                return
            }
            attempt = 0
            setConnected(true)
            // Registrasi meja ke server kasir (ip dipakai kasir untuk
            // menandai mode pairing hanya pada TV yang sedang di-pair).
            val reg = JSONObject()
                .put("type", "REGISTER")
                .put("meja_id", mejaId)
                .put("device", "android_tv")
                .put("nama", mejaId)
                .put("ip", NetUtil.localIpv4(appContext))
            ws.send(reg.toString())
        }

        override fun onMessage(ws: WebSocket, text: String) {
            if (closedByUser || ws !== webSocket) return
            val msg = ServerMessage.fromJson(text)
            // Balas PONG utk heartbeat server kasir — tanpa ini server menganggap
            // client mati (last_seen usang) & badge CLI di kasir jadi ✗.
            if (msg?.action == Actions.PING) {
                try {
                    ws.send("""{"type":"PONG"}""")
                } catch (_: Exception) {
                }
            }
            msg?.let { onMessage(it) }
        }

        override fun onClosed(ws: WebSocket, code: Int, reason: String) {
            if (ws !== webSocket) return
            webSocket = null
            setConnected(false)
            scheduleReconnect("ditutup server: $reason")
        }

        override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
            if (ws !== webSocket) return
            webSocket = null
            setConnected(false)
            scheduleReconnect("gagal: ${t.message ?: t.javaClass.simpleName}")
        }
    }

    private fun scheduleReconnect(alasan: String = "") {
        if (closedByUser) return
        reconnectHandler.removeCallbacksAndMessages(null)
        val delayMs = minOf(10_000L, 2_000L * (1L shl minOf(attempt, 3)))
        attempt += 1
        android.util.Log.w("RRTVService",
            "WebSocket putus ($alasan) — coba lagi dalam ${delayMs / 1000} dtk")
        reconnectHandler.postDelayed({ connect() }, delayMs)
    }

    private fun setConnected(value: Boolean) {
        if (connected == value) return
        connected = value
        android.util.Log.i("RRTVService",
            if (value) "WebSocket tersambung ke $host:$port"
            else "WebSocket terputus dari $host:$port")
        mainHandler.post { onStatusChanged(value) }
    }
}
