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
    const val SHOW_MEDIA = "SHOW_MEDIA"
    const val HIDE_MEDIA = "HIDE_MEDIA"
    const val PING = "PING"
}

data class BillLine(
    val item: String,
    val harga: String,
)

data class LockDetail(
    val meja: String,
    val sewa: String,
    val fnb: String,
    val total: String,
    val sewaHarga: String = "",
    val makanan: List<BillLine> = emptyList(),
    val minuman: List<BillLine> = emptyList(),
    val logoUrl: String = "",
    val promoUrl: String = "",
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
    val pesan: String,
    val detail: LockDetail?,
    val mediaType: String,
    val mediaUrl: String,
    val overlayMode: String,
    val overlayLastMinutes: Int,
    val logoUrl: String,
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
                        makanan = d.optJSONArray("makanan")?.let { arr ->
                            List(arr.length()) { i ->
                                val line = arr.optJSONObject(i)
                                BillLine(
                                    line?.optString("item", "") ?: "",
                                    line?.optString("harga", "") ?: "",
                                )
                            }
                        } ?: emptyList(),
                        minuman = d.optJSONArray("minuman")?.let { arr ->
                            List(arr.length()) { i ->
                                val line = arr.optJSONObject(i)
                                BillLine(
                                    line?.optString("item", "") ?: "",
                                    line?.optString("harga", "") ?: "",
                                )
                            }
                        } ?: emptyList(),
                        logoUrl = d.optString("logo_url", ""),
                        promoUrl = d.optString("promo_url", ""),
                    ) else null

                    ServerMessage(
                        action = o.getString("action"),
                        mejaId = o.optString("meja_id", ""),
                        sisaDetik = o.optInt("sisa_detik", 0),
                        namaRental = o.optString("nama_rental", "RR Billing Pro"),
                        totalTagihan = o.optString("total_tagihan", "Rp 0"),
                        pesan = o.optString("pesan", "WAKTU SEWA HABIS"),
                        detail = detail,
                        mediaType = o.optString("type", ""),
                        mediaUrl = o.optString("url", ""),
                        overlayMode = o.optString("overlay_mode", "always"),
                        overlayLastMinutes = o.optInt("overlay_last_minutes", 5),
                        logoUrl = o.optString("logo_url", ""),
                    )
                }
            } catch (e: Exception) {
                null
            }
        }
    }
}
