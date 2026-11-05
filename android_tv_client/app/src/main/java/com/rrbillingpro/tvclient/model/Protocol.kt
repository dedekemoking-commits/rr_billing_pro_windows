package com.rrbillingpro.tvclient.model

import org.json.JSONObject

/**
 * Protokol JSON antara server kasir (TvWsHub) dan client TV.
 * Lihat tv_ws_hub.py di sisi server untuk kontrak lengkap.
 */
object Actions {
    const val START_TIMER = "START_TIMER"
    const val PAUSE_TIMER = "PAUSE_TIMER"
    const val RESUME_TIMER = "RESUME_TIMER"
    const val STOP_TIMER = "STOP_TIMER"
    const val UPDATE_TOTAL = "UPDATE_TOTAL"
    const val SYNC_TIMER = "SYNC_TIMER"
    const val LOCK_SCREEN = "LOCK_SCREEN"
    const val UNLOCK_SCREEN = "UNLOCK_SCREEN"
    const val UPDATE_LOGO = "UPDATE_LOGO"
    const val UPDATE_RENTAL = "UPDATE_RENTAL"
    const val SHOW_MEDIA = "SHOW_MEDIA"
    const val HIDE_MEDIA = "HIDE_MEDIA"

    /**
     * Banner pesan singkat dari kasir (v4.17), mis. "Mohon Jangan Ribut".
     * Field: `pesan` (teks) + `durasi` (detik, default 5). Overlay atas
     * transparan, hilang sendiri — game/HDMI di belakang tetap jalan.
     */
    const val SHOW_MESSAGE = "SHOW_MESSAGE"
    const val SHOW_PIN = "SHOW_PIN"
    const val HIDE_PIN = "HIDE_PIN"
    const val SHOW_QR = "SHOW_QR"
    const val HIDE_QR = "HIDE_QR"
    const val UPDATE_LOCK_BG = "UPDATE_LOCK_BG"
    const val OVERLAY_STYLE = "OVERLAY_STYLE"
    const val OVERLAY_SETTINGS = "OVERLAY_SETTINGS"
    const val SLEEP_TV = "SLEEP_TV"
    const val PICK_MEDIA = "PICK_MEDIA"
    const val DELETE_MEDIA = "DELETE_MEDIA"
    const val PING = "PING"
    const val QUERY_SCREEN_STATE = "QUERY_SCREEN_STATE"

    /** Monitoring jarak jauh dari APK RR Monitor (via kasir/Firestore). */
    const val REPORT_LOGS = "REPORT_LOGS"
    const val RECONNECT_WS = "RECONNECT_WS"
    const val RESTART_CLIENT = "RESTART_CLIENT"

    /**
     * Mode pairing sedang berjalan di kasir untuk IP tertentu. Selama aktif,
     * TV tidak boleh mengirim power key / memutar promo / membuka lockscreen,
     * karena dialog kode pairing sistem Android TV langsung hilang begitu
     * window atau layar berubah.
     */
    const val PAIRING_MODE = "PAIRING_MODE"
}

data class BillLine(
    val item: String,
    val harga: String,
    val lunas: Boolean = true,
)

data class LockDetail(
    val meja: String,
    val sewa: String,
    val fnb: String,
    val total: String,
    val sewaHarga: String = "",
    val sewaLunas: Boolean = true,
    val lunasTotal: String = "",
    val tagihanTotal: String = "",
    val makanan: List<BillLine> = emptyList(),
    val minuman: List<BillLine> = emptyList(),
    val logoUrl: String = "",
    val promoUrl: String = "",
    /** Judul lockscreen; server memakai "LAST TIME HABIS" saat Last Time selesai. */
    val pesan: String = "WAKTU SEWA HABIS",
    /** Pesan tambahan di bawah judul (mis. "Silahkan tambah sesi waktu anda."). */
    val notice: String = "",
    /** Gambar khusus lockscreen Last Time (kosong = pakai background biasa). */
    val lastTimeImageUrl: String = "",
)

/**
 * Satu pesan dari server. `action` menentukan tipe; field lain bersifat
 * opsional sesuai action. Parsing dibuat toleran (tidak crash pada field
 * yang hilang).
 */
data class ServerMessage(
    val action: String,
    val mejaId: String,
    val sisaDetik: Int,
    val namaRental: String,
    val totalTagihan: String,
    val lunasTotal: String,
    val tagihanTotal: String,
    val pesan: String,
    val detail: LockDetail?,
    val mediaType: String,
    val mediaUrl: String,
    val overlayMode: String,
    val overlayLastMinutes: Int,
    val logoUrl: String,
    val pin: String = "",
    val reconnect: Boolean = false,
    val forceStart: Boolean = false,
    val grup: String = "",
    val bgUrl: String = "",
    val pairing: Boolean = false,
    val targetIp: String = "",
    // Main Bebas: detik sejak sesi mulai (dari kasir, bukan dihitung TV)
    val isBebas: Boolean = false,
    val elapsedDetik: Int = -1,
    val bebasStartDurasi: Int = 5,
    val bebasInterval: Int = 60,
    val bebasDurasi: Int = 10,
    val popupDetik: Int = 0,
    val countdown: Int = 0,
    // Gaya popup dari kasir. Nilai -1 / "" = pakai nilai tersimpan di TV.
    val bgAlpha: Int = -1,
    val accent: String = "",
    val radius: Int = -1,
    val timerSize: Int = -1,
    val scale: Int = -1,
    val posY: Int = -1,
    /**
     * Port HDMI pilihan kasir per TV (v4.13):
     *   1..4 = pindah otomatis setelah promo selesai
     *   0    = belum diisi -> app TIDAK menyentuh input
     *  -1    = "Jangan pakai" -> TV yang mengatur inputnya sendiri
     * Int.MIN_VALUE = field TIDAK dikirim (kasir lama) -> Prefs tidak diubah.
     */
    val hdmiPort: Int = Int.MIN_VALUE,
    /** Id input firmware untuk port di atas (hasil peta otomatis kasir). */
    val hdmiInputHint: String = "",
    /** Nama file aset lokal di folder media (v4.13) — mis. promo.mp4. */
    val local: String = "",
    /** Durasi tampil banner SHOW_MESSAGE (detik) — default 5, batas 3-300. */
    val durasi: Int = 5,
    val noWake: Boolean = false,
    /** True saat kasir memberi tambahan waktu Last Time (popup wajib tampil). */
    val isLastTime: Boolean = false,
) {
    companion object {
        fun fromJson(raw: String): ServerMessage? {
            return try {
                val o = JSONObject(raw)

                // Pesan non-action (REGISTERED, ERROR, dsb) diabaikan di sini.
                if (!o.has("action")) {
                    null
                } else {
                    val d = o.optJSONObject("detail_transaksi")
                    val detail = if (d != null) LockDetail(
                        meja = d.optString("meja", "-"),
                        sewa = d.optString("sewa", "-"),
                        fnb = d.optString("fnb", "Rp 0"),
                        total = d.optString("total", "Rp 0"),
                        sewaHarga = d.optString("sewa_harga", ""),
                        sewaLunas = d.optBoolean("sewa_lunas", true),
                        lunasTotal = d.optString("lunas_total", ""),
                        tagihanTotal = d.optString("tagihan_total", ""),
                        makanan = d.optJSONArray("makanan")?.let { arr ->
                            List(arr.length()) { i ->
                                val line = arr.optJSONObject(i)
                                BillLine(
                                    line?.optString("item", "") ?: "",
                                    line?.optString("harga", "") ?: "",
                                    line?.optBoolean("lunas", true) ?: true,
                                )
                            }
                        } ?: emptyList(),
                        minuman = d.optJSONArray("minuman")?.let { arr ->
                            List(arr.length()) { i ->
                                val line = arr.optJSONObject(i)
                                BillLine(
                                    line?.optString("item", "") ?: "",
                                    line?.optString("harga", "") ?: "",
                                    line?.optBoolean("lunas", true) ?: true,
                                )
                            }
                        } ?: emptyList(),
                        logoUrl = d.optString("logo_url", ""),
                        promoUrl = d.optString("promo_url", ""),
                        pesan = d.optString("pesan", "WAKTU SEWA HABIS"),
                        notice = d.optString("notice", ""),
                        lastTimeImageUrl = d.optString("last_time_image_url", ""),
                    ) else null

                    ServerMessage(
                        action = o.getString("action"),
                        mejaId = o.optString("meja_id", ""),
                        sisaDetik = o.optInt("sisa_detik", 0),
                        namaRental = o.optString("nama_rental", "RR Billing Pro"),
                        totalTagihan = o.optString("total_tagihan", "Rp 0"),
                        lunasTotal = o.optString("lunas_total", ""),
                        tagihanTotal = o.optString("tagihan_total", ""),
                        pesan = o.optString("pesan", "WAKTU SEWA HABIS"),
                        detail = detail,
                        mediaType = o.optString("type", ""),
                        mediaUrl = o.optString("url", ""),
                        overlayMode = o.optString("overlay_mode", "always"),
                        overlayLastMinutes = o.optInt("overlay_last_minutes", 5),
                        logoUrl = o.optString("logo_url", ""),
                        pin = o.optString("pin", ""),
                        reconnect = o.optBoolean("reconnect", false),
                        forceStart = o.optBoolean("force_start", false),
                        grup = o.optString("grup", ""),
                        bgUrl = o.optString("bg_url", ""),
                        pairing = o.optBoolean("pairing", false),
                        targetIp = o.optString("ip", ""),
                        isBebas = o.optBoolean("is_bebas", o.optBoolean("isBebas", false)),
                        elapsedDetik = o.optInt("elapsed_detik", -1),
                        bebasStartDurasi = o.optInt("bebas_start_durasi", 5).coerceAtLeast(0),
                        bebasInterval = o.optInt("bebas_interval", 60).coerceAtLeast(1),
                        bebasDurasi = o.optInt("bebas_durasi", 10).coerceAtLeast(1),
                        popupDetik = o.optInt("popup_detik", 0).coerceIn(0, 60),
                        countdown = o.optInt("countdown", 0).coerceAtLeast(0),
                        bgAlpha = o.optInt("bg_alpha", -1),
                        accent = o.optString("accent", ""),
                        radius = o.optInt("radius", -1),
                        timerSize = o.optInt("timer_size", -1),
                        scale = o.optInt("scale", -1),
                        posY = o.optInt("pos_y", -1),
                        hdmiPort = o.optInt("hdmi_port", Int.MIN_VALUE),
                        hdmiInputHint = o.optString("hdmi_input_hint", ""),
                        local = o.optString("local", ""),
                        durasi = o.optInt("durasi", 5),
                        noWake = o.optBoolean("no_wake", false),
                        isLastTime = o.optBoolean("is_last_time", false),
                    )
                }
            } catch (e: Exception) {
                null
            }
        }
    }
}
