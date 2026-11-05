package com.rrbillingpro.tvclient.net

import android.content.Context
import android.util.Log
import com.rrbillingpro.tvclient.util.Prefs
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.File
import java.io.InputStream
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

class MediaUploadServer(
    private val context: Context,
    private val port: Int = 8089,
    private val onUploaded: (String) -> Unit,
) {
    private val running = AtomicBoolean(false)
    private var serverSocket: ServerSocket? = null
    private var worker: Thread? = null

    private val allowed = setOf(
        "promo.mp4", "promo.jpg", "promo.png",
        "lockscreen.mp4", "lockscreen.jpg", "lockscreen.png",
        "logo.png",
    )

    fun start() {
        if (!running.compareAndSet(false, true)) return
        try {
            serverSocket = ServerSocket(port)
        } catch (e: Exception) {
            running.set(false)
            Log.w("MediaUpload", "gagal bind port $port: ${e.message}")
            return
        }
        worker = thread(name = "media-upload", isDaemon = true) {
            while (running.get()) {
                val ss = serverSocket ?: break
                try {
                    val socket = ss.accept()
                    try {
                        handle(socket)
                    } catch (e: Exception) {
                        Log.w("MediaUpload", "request gagal: ${e.message}")
                    } finally {
                        try { socket.close() } catch (_: Exception) {}
                    }
                } catch (e: Exception) {
                    if (running.get()) Log.w("MediaUpload", "accept gagal: ${e.message}")
                }
            }
        }
    }

    fun stop() {
        running.set(false)
        try { serverSocket?.close() } catch (_: Exception) {}
        serverSocket = null
        worker = null
    }

    private fun handle(socket: Socket) {
        val input = BufferedInputStream(socket.getInputStream())
        val header = readHeader(input) ?: return
        val lines = header.split("\r\n")
        val first = lines.firstOrNull() ?: return
        val parts = first.split(" ")
        if (parts.size < 2) return
        val method = parts[0].uppercase()
        val path = parts[1]
        val headers = HashMap<String, String>()
        for (i in 1 until lines.size) {
            val idx = lines[i].indexOf(':')
            if (idx > 0) headers[lines[i].substring(0, idx).trim().lowercase()] =
                lines[i].substring(idx + 1).trim()
        }
        val out = BufferedOutputStream(socket.getOutputStream())
        when {
            method == "GET" && path.startsWith("/info") -> writeJson(out, infoJson())
            method == "POST" && path.startsWith("/upload") -> {
                val name = queryParam(path, "name")?.trim().orEmpty()
                if (name !in allowed) {
                    writeJson(out, JSONObject().put("ok", false).put("error", "nama file tidak diizinkan").toString(), 400)
                    return
                }
                val length = headers["content-length"]?.toLongOrNull() ?: -1L
                if (length <= 0 || length > 300L * 1024L * 1024L) {
                    writeJson(out, JSONObject().put("ok", false).put("error", "ukuran tidak valid").toString(), 400)
                    return
                }
                val target = Prefs.mediaFile(context, name)
                target.parentFile?.mkdirs()
                val tmp = File(target.parentFile, ".$name.part")
                var received = 0L
                BufferedOutputStream(tmp.outputStream()).use { fileOut ->
                    val buf = ByteArray(64 * 1024)
                    while (received < length) {
                        val want = minOf(buf.size.toLong(), length - received).toInt()
                        val n = input.read(buf, 0, want)
                        if (n <= 0) break
                        fileOut.write(buf, 0, n)
                        received += n
                    }
                }
                if (received != length) {
                    tmp.delete()
                    writeJson(out, JSONObject().put("ok", false).put("error", "upload terputus").toString(), 400)
                    return
                }
                if (!tmp.renameTo(target)) {
                    try {
                        tmp.copyTo(target, overwrite = true)
                        tmp.delete()
                    } catch (e: Exception) {
                        tmp.delete()
                        writeJson(out, JSONObject().put("ok", false).put("error", "gagal menyimpan").toString(), 500)
                        return
                    }
                }
                try { onUploaded(name) } catch (_: Exception) {}
                writeJson(out, JSONObject().put("ok", true).put("file", name).put("size", target.length()).toString())
            }
            else -> writeJson(out, JSONObject().put("ok", false).put("error", "not found").toString(), 404)
        }
        out.flush()
    }

    private fun infoJson(): String {
        val o = JSONObject().put("ok", true).put("port", port)
        val files = JSONObject()
        for (name in allowed) {
            val f = Prefs.mediaFile(context, name)
            if (f.exists()) files.put(name, f.length())
        }
        o.put("files", files)
        return o.toString()
    }

    private fun queryParam(path: String, key: String): String? {
        val q = path.substringAfter('?', "")
        if (q.isBlank()) return null
        for (part in q.split('&')) {
            val kv = part.split('=', limit = 2)
            if (kv.size == 2 && kv[0] == key) return URLDecoder.decode(kv[1], "UTF-8")
        }
        return null
    }

    private fun readHeader(input: InputStream): String? {
        val bytes = ArrayList<Byte>(1024)
        var state = 0
        while (bytes.size < 64 * 1024) {
            val b = input.read()
            if (b < 0) return null
            bytes.add(b.toByte())
            state = when {
                state == 0 && b == '\r'.code -> 1
                state == 1 && b == '\n'.code -> 2
                state == 2 && b == '\r'.code -> 3
                state == 3 && b == '\n'.code -> 4
                b == '\r'.code -> 1
                else -> 0
            }
            if (state == 4) return String(bytes.toByteArray(), Charsets.ISO_8859_1)
        }
        return null
    }

    private fun writeJson(out: BufferedOutputStream, json: String, code: Int = 200) {
        val body = json.toByteArray(Charsets.UTF_8)
        val status = when (code) {
            400 -> "400 Bad Request"
            404 -> "404 Not Found"
            500 -> "500 Internal Server Error"
            else -> "200 OK"
        }
        val head = "HTTP/1.1 $status\r\n" +
            "Content-Type: application/json; charset=utf-8\r\n" +
            "Content-Length: ${body.size}\r\n" +
            "Connection: close\r\n\r\n"
        out.write(head.toByteArray(Charsets.US_ASCII))
        out.write(body)
    }
}
