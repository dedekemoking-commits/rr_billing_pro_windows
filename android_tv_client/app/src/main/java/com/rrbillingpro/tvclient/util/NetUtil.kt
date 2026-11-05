package com.rrbillingpro.tvclient.util

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager

/** Utilitas jaringan sederhana untuk client TV. */
object NetUtil {

    /**
     * IPv4 lokal perangkat (WiFi/LAN), atau string kosong bila belum tersambung.
     * Dipakai saat REGISTER ke server kasir supaya kasir tahu IP TV ini —
     * dipakai untuk menandai mode pairing hanya pada TV yang sedang di-pair.
     */
    fun localIpv4(ctx: Context): String {
        try {
            val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            val ip = wm?.connectionInfo?.ipAddress ?: 0
            if (ip != 0) {
                return String.format(
                    "%d.%d.%d.%d",
                    ip and 0xff,
                    (ip shr 8) and 0xff,
                    (ip shr 16) and 0xff,
                    (ip shr 24) and 0xff,
                )
            }
        } catch (_: Exception) {
        }
        try {
            val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
                ?: return ""
            val net = cm.activeNetwork ?: return ""
            val caps = cm.getNetworkCapabilities(net) ?: return ""
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
            ) {
                val addr = cm.getLinkProperties(net)?.linkAddresses?.firstOrNull()?.address
                if (addr != null && addr.address.size == 4) {
                    val b = addr.address
                    return "${b[0].toInt() and 0xff}.${b[1].toInt() and 0xff}." +
                        "${b[2].toInt() and 0xff}.${b[3].toInt() and 0xff}"
                }
            }
        } catch (_: Exception) {
        }
        return ""
    }
}
