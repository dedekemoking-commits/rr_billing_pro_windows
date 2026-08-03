package com.rrbillingpro.tvclient

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import com.rrbillingpro.tvclient.overlay.OverlayWidget
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

    private val statusHandler = Handler(Looper.getMainLooper())
    private val statusRunnable = object : Runnable {
        override fun run() {
            refreshStatus()
            statusHandler.postDelayed(this, 2000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        etHost = findViewById(R.id.et_server_ip)
        etPort = findViewById(R.id.et_server_port)
        etMeja = findViewById(R.id.et_meja_id)
        tvStatus = findViewById(R.id.tv_status)
        tvNote = findViewById(R.id.tv_overlay_note)

        etHost.setText(Prefs.host(this))
        etPort.setText(Prefs.port(this).toString())
        etMeja.setText(Prefs.mejaId(this))

        findViewById<Button>(R.id.btn_save_start).setOnClickListener {
            saveAndStart()
        }
        findViewById<Button>(R.id.btn_stop).setOnClickListener {
            TvOverlayService.stop(this)
        }
        findViewById<Button>(R.id.btn_overlay_perm).setOnClickListener {
            requestOverlayPermission()
        }

        requestNotificationPermission()
    }

    override fun onResume() {
        super.onResume()
        TvOverlayService.instance?.addListener(this)
        statusHandler.post(statusRunnable)
        refreshStatus()
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

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            tvNote.text = "⚠ Izin overlay belum aktif — overlay tidak akan muncul. " +
                    "Tekan 'IZIN OVERLAY' lalu izinkan."
            requestOverlayPermission()
        } else {
            tvNote.text = ""
        }

        TvOverlayService.start(this)
        refreshStatus()
    }

    private fun requestOverlayPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            val uri = Uri.parse("package:$packageName")
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, uri))
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
    }

    // ── Service state listener ───────────────────────────────────────────────
    override fun onLockChanged(locked: Boolean) {
        runOnUiThread { refreshStatus() }
    }

    override fun onStatusChanged(connected: Boolean) {
        runOnUiThread { refreshStatus() }
    }
}
