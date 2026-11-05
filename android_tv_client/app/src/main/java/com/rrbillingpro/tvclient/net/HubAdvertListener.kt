package com.rrbillingpro.tvclient.net

import android.util.Log
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException

/**
 * Auto-discovery hub kasir (v4.14).
 *
 * Kasir memancarkan alamat hub lewat UDP broadcast ke port [PORT] tiap
 * beberapa detik (`tv_ws_hub.py` -> ADVERT_PORT). Listener ini mendengarkan
 * dan memberi tahu service saat alamat hub BERBEDA dengan yang tersimpan —
 * service lalu pindah alamat & reconnect otomatis.
 *
 * Manfaat: ganti IP PC / IP DHCP berubah tidak lagi membuat TV "buta" —
 * popup waktu, kunci, dan perintah kasir langsung jalan begitu alamat baru
 * ditemukan (snapshot sesi dikirim server saat reconnect).
 */
class HubAdvertListener(
    private val onHub: (host: String, port: Int) -> Unit,
) {
    companion object {
        private const val TAG = "RRHubAdvert"
        private const val PORT = 8095
        private const val APP_ID = "rrbillingpro"
    }

    private var thread: Thread? = null

    @Volatile
    private var running = false

    fun start() {
        if (running) return
        running = true
        thread = Thread({ loop() }, "hub-advert").apply {
            isDaemon = true
            start()
        }
    }

    fun stop() {
        running = false
        thread?.interrupt()
        thread = null
    }

    private fun loop() {
        var sock: DatagramSocket? = null
        try {
            sock = DatagramSocket(null).apply {
                reuseAddress = true
                broadcast = true
                soTimeout = 2000
                bind(InetSocketAddress(PORT))
            }
            Log.i(TAG, "mendengarkan alamat hub di UDP :$PORT")
            val buf = ByteArray(2048)
            while (running) {
                try {
                    val pkt = DatagramPacket(buf, buf.size)
                    sock.receive(pkt)
                    val txt = String(pkt.data, 0, pkt.length, Charsets.UTF_8)
                    val o = try {
                        JSONObject(txt)
                    } catch (_: Exception) {
                        continue
                    }
                    if (o.optString("app") != APP_ID) continue
                    if (o.optString("type") != "hub_advert") continue
                    val host = o.optString("host").trim()
                    val port = o.optInt("port", 0)
                    if (host.isBlank() || port <= 0) continue
                    onHub(host, port)
                } catch (_: SocketTimeoutException) {
                    // timeout normal: lanjut cek `running`
                } catch (e: Exception) {
                    if (!running) break
                    Log.w(TAG, "receive gagal: ${e.message}")
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "listener hub gagal start: ${e.message}")
        } finally {
            try {
                sock?.close()
            } catch (_: Exception) {
            }
        }
    }
}
