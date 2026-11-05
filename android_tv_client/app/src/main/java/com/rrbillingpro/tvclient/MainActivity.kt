package com.rrbillingpro.tvclient

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.google.firebase.ktx.Firebase
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.SetOptions
import com.google.firebase.FirebaseApp
import com.rrbillingpro.tvclient.lockscreen.LockScreenActivity
import com.rrbillingpro.tvclient.overlay.OverlayWidget
import com.rrbillingpro.tvclient.permission.OverlayPermission
import com.rrbillingpro.tvclient.permission.PermissionKit
import com.rrbillingpro.tvclient.service.TvOverlayService
import com.rrbillingpro.tvclient.util.Prefs

/**
 * Layar setup di STB:
 *  1. Isi IP server kasir, port WebSocket, dan meja_id (sesuai nama TV di kasir).
 *  2. Simpan & mulai Foreground Service (WebSocket + overlay + lockscreen).
 *  3. Tombol untuk memberi izin overlay (SYSTEM_ALERT_WINDOW).
 */
class MainActivity : Activity(), TvOverlayService.StateListener {

    private lateinit var etHost: EditText
    private lateinit var etPort: EditText
    private lateinit var etMeja: EditText
    private lateinit var tvStatus: TextView
    private lateinit var tvNote: TextView
    private lateinit var tvIzinRingkas: TextView
    private lateinit var llIzinDaftar: LinearLayout
    private lateinit var tvIzinPanduan: TextView

    private val statusHandler = Handler(Looper.getMainLooper())
    private val statusRunnable = object : Runnable {
        override fun run() {
            refreshStatus()
            segarkanPanelIzin()
            statusHandler.postDelayed(this, 2000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Inisialisasi Firebase App (Critical: sebaliknya app crash dengan
        // "Default FirebaseApp is not initialized in this process").
        FirebaseApp.initializeApp(this)
        setContentView(R.layout.activity_main)

        etHost = findViewById(R.id.et_server_ip)
        etPort = findViewById(R.id.et_server_port)
        etMeja = findViewById(R.id.et_meja_id)
        tvStatus = findViewById(R.id.tv_status)
        tvNote = findViewById(R.id.tv_overlay_note)
        tvIzinRingkas = findViewById(R.id.tv_izin_ringkas)
        llIzinDaftar = findViewById(R.id.ll_izin_daftar)
        tvIzinPanduan = findViewById(R.id.tv_izin_panduan)
        val etLockBg = findViewById<EditText>(R.id.et_lock_bg_url)
        etLockBg.setText(Prefs.lockBgUrl(this))

        etHost.setText(Prefs.host(this))
        etPort.setText(Prefs.port(this).toString())
        etMeja.setText(Prefs.mejaId(this))

        findViewById<Button>(R.id.btn_save_start).setOnClickListener {
            saveAndStart()
        }
        findViewById<Button>(R.id.btn_stop).setOnClickListener {
            // v4.13: STOP juga mematikan auto-start. Kontrak dengan kasir:
            // selama autoStart true, kasir boleh "menghidupkan ulang" app dari
            // latar belakang lewat adb (am start) — kalau kasir sengaja STOP,
            // auto-start harus mati supaya app tidak hidup kembali sendiri.
            Prefs.saveAutoStart(this, false)
            TvOverlayService.stop(this)
        }
        findViewById<Button>(R.id.btn_overlay_perm).setOnClickListener {
            requestOverlayPermission()
        }
        findViewById<Button>(R.id.btn_cek_izin).setOnClickListener {
            segarkanPanelIzin()
            Toast.makeText(this, "Memeriksa ulang kelengkapan izin…",
                Toast.LENGTH_SHORT).show()
        }
        findViewById<Button>(R.id.btn_lock_bg).setOnClickListener {
            val url = etLockBg.text.toString().trim()
            Prefs.saveLockBg(this, url)
            LockScreenActivity.updateBgUrl(url)
            Toast.makeText(
                this,
                if (url.isBlank()) "Background lockscreen dikosongkan (pakai bawaan)"
                else "Background lockscreen diperbarui",
                Toast.LENGTH_LONG
            ).show()
        }

        requestNotificationPermission()
        segarkanPanelIzin()

        // Beri fokus awal ke ScrollView, bukan EditText pertama: dengan begitu
        // remote TV bisa menggulir ke panel izin di bawah tanpa harus menekan
        // D-pad ↓ belasan kali (dan tanpa Risko keyboard muncul sendiri).
        findViewById<android.view.View>(R.id.scroll_setup)?.requestFocus()
    }

    // ══════════════════════════════════════════════════════════════════
    //  PANEL KELENGKAPAN IZIN & SETTING
    // ══════════════════════════════════════════════════════════════════

    /**
     * Tampilkan daftar izin/setting wajib beserta status ✅/❌ dan tombol
     * "Buka" yang mengarah ke halaman pengaturan resmi di TV.
     *
     * Semua baris diperbarui otomatis tiap 2 detik (statusRunnable), jadi
     * begitu kasir mengubah izin di TV, status langsung hijau tanpa perlu
     * membuka ulang aplikasi.
     */
    private fun segarkanPanelIzin() {
        try {
            val items = PermissionKit.periksaSemua(this)
            PermissionKit.catatKeServer(this, items)

            val (ok, belum) = PermissionKit.ringkas(items)
            tvIzinRingkas.text = "Siap $ok dari ${items.size}   •   Belum: $belum"
            tvIzinRingkas.setTextColor(if (belum == 0) Color.parseColor("#00D68F")
                                        else Color.parseColor("#FFAA00"))

            llIzinDaftar.removeAllViews()
            val dp = (resources.displayMetrics.density * 10).toInt()

            for (item in items) {
                val row = LinearLayout(this)
                row.orientation = LinearLayout.HORIZONTAL
                row.setPadding(dp / 2, dp / 3, dp / 2, dp / 3)

                val ikon = TextView(this)
                ikon.text = if (item.ok) "✅" else if (item.manual) "⚠️" else "❌"
                ikon.setTextColor(if (item.ok) Color.parseColor("#00D68F")
                                   else Color.parseColor("#FF6B6B"))
                ikon.textSize = 16f
                row.addView(ikon, LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))

                val teks = TextView(this)
                val tandaManual = if (item.manual && !item.ok) "  (manual)" else ""
                teks.text = "${item.judul}\n${item.keterangan}${tandaManual}\n↳ ${item.aksi}"
                teks.setTextColor(Color.WHITE)
                teks.textSize = 11f
                teks.setPadding(dp / 2, 0, dp / 2, 0)
                row.addView(teks, LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))

                if (!item.ok) {
                    val btn = Button(this)
                    btn.text = "Buka"
                    btn.textSize = 11f
                    btn.setPadding(dp, dp / 4, dp, dp / 4)
                    btn.setOnClickListener { PermissionKit.buka(this, item.key) }
                    row.addView(btn, LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
                }
                llIzinDaftar.addView(row, LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT))
            }

            // Panduan langkah demi langkah untuk yang belum siap.
            tvIzinPanduan.text = if (belum == 0) {
                "✅ Semua izin siap — client TV siap terhubung ke server kasir."
            } else {
                panduanIzin(items)
            }

            // Kabari kasir begitu saja status berubah, supaya kasir
            // bisa menampilkan/memperbaiki izin TV tanpa cek manual.
            TvOverlayService.instance?.laporkanIzinKeKasir()
        } catch (e: Exception) {
            tvIzinRingkas.text = "Gagal memeriksa izin: ${e.message}"
        }
    }

    /** Susun teks langkah perbaikan berurutan untuk izin yang belum siap. */
    private fun panduanIzin(items: List<PermissionKit.Item>): String {
        val belum = items.filter { !it.ok }
        if (belum.isEmpty()) return ""
        val sb = StringBuilder("LANGKAH PERBAIKAN:\n")
        belum.forEachIndexed { i, item ->
            sb.append("${i + 1}. ${item.judul}\n     ${item.aksi}\n")
        }
        sb.append("\nTips: dari kasir klik tombol ⚙ IZIN pada kartu TV — ")
        sb.append("aplikasi akan mencoba mengaktifkannya otomatis lewat ADB.")
        return sb.toString()
    }

    override fun onResume() {
        super.onResume()
        // Auto-pulihkan service: kalau service mati (ROM membunuhnya, atau TV
        // restart) dan autoStart aktif, nyalakan lagi dari sini. Tanpa ini
        // kasir harus tekan tombol SIMPAN setiap kali service hilang.
        pulihkanServiceJikaMati()
        TvOverlayService.instance?.addListener(this)
        statusHandler.post(statusRunnable)
        refreshStatus()
        segarkanPanelIzin()
    }

    private fun pulihkanServiceJikaMati() {
        try {
            if (!Prefs.autoStart(this)) return
            if (TvOverlayService.instance != null) return
            if (TvOverlayService.isRunning(this)) return
            TvOverlayService.start(this)
        } catch (_: Exception) {
        }
    }

    override fun onPause() {
        super.onPause()
        statusHandler.removeCallbacks(statusRunnable)
        TvOverlayService.instance?.removeListener(this)
    }

    private fun saveAndStart() {
        val host = etHost.text.toString().trim()
        val port = etPort.text.toString().trim().toIntOrNull() ?: 8080
        val meja = etMeja.text.toString().trim()
        if (host.isEmpty() || meja.isEmpty()) {
            tvStatus.text = "IP server dan ID meja wajib diisi!"
            return
        }
        Prefs.save(this, host, port, meja, autoStart = true)
        Prefs.saveAutoStart(this, true)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !OverlayPermission.isGranted(this)) {
            tvNote.text = "⚠ " + OverlayPermission.guideText()
        } else {
            tvNote.text = ""
        }

        TvOverlayService.start(this)
        refreshStatus()
        Toast.makeText(this, "Pengaturan disimpan & service dimulai", Toast.LENGTH_LONG).show()
    }

    private fun requestOverlayPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !OverlayPermission.isGranted(this)) {
            OverlayPermission.request(this)
        } else {
            tvNote.text = "Izin overlay sudah aktif ✓"
        }
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
        }
    }

    private fun refreshStatus() {
        val svc = TvOverlayService.instance
        val running = TvOverlayService.isRunning(this)
        val sb = StringBuilder()

        if (running) {
            sb.append("Service: AKTIF\n")
            sb.append("Server: ${Prefs.host(this)}:${Prefs.port(this)}\n")
            sb.append("Meja: ${Prefs.mejaId(this)}\n")
            val connected = svc?.isConnected ?: false
            sb.append(if (connected) "WebSocket: TERHUBUNG ✓" else "WebSocket: mencoba konek…")
            val locked = svc?.isLocked ?: false
            if (locked) sb.append("\nLockscreen: TERKUNCI")
            if (running && svc == null) sb.append("\n(service menyala, menunggu koneksi)")
        } else {
            sb.append("Service: mati")
        }

        tvStatus.text = sb.toString()
        refreshOverlayNote()
    }

    /**
     * Label izin overlay diperbarui OTOMATIS tiap 2 detik (statusRunnable),
     * jadi tidak pernah basi: begitu izin diaktifkan di Pengaturan, label
     * langsung berubah hijau tanpa perlu buka ulang aplikasi.
     */
    private fun refreshOverlayNote() {
        val granted = OverlayPermission.isGranted(this)
        tvNote.text = if (granted) {
            "Izin overlay aktif ✓"
        } else {
            "⚠ " + OverlayPermission.guideText()
        }
    }

    // ── Service state listener ───────────────────────────────────────────────
    override fun onLockChanged(locked: Boolean) {
        runOnUiThread { refreshStatus() }
    }

    override fun onStatusChanged(connected: Boolean) {
        runOnUiThread { refreshStatus() }
    }

}
