package com.rrbillingpro.tvclient.media

import android.Manifest
import com.rrbillingpro.tvclient.service.TvOverlayService
import android.app.Activity
import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import com.rrbillingpro.tvclient.util.Prefs
import java.io.File

class MediaPickerActivity : Activity() {

    private data class VideoItem(val uri: Uri, val name: String, val size: Long)

    private lateinit var listView: ListView
    private lateinit var status: TextView
    private lateinit var pickButton: Button
    private val videos = mutableListOf<VideoItem>()
    private var mediaType = "promo"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        mediaType = intent.getStringExtra(EXTRA_TYPE).orEmpty().ifBlank { "promo" }
        setContentView(buildUi())
        if (hasPermission()) loadVideos() else requestPermission()
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(56, 36, 56, 36)
            setBackgroundColor(Color.rgb(12, 20, 28))
        }
        val title = TextView(this).apply {
            text = if (mediaType == "lockscreen") "PILIH VIDEO LOCKSCREEN" else "PILIH VIDEO PROMOSI"
            setTextColor(Color.WHITE)
            textSize = 28f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        }
        status = TextView(this).apply {
            setTextColor(Color.rgb(255, 209, 102))
            textSize = 17f
            setPadding(0, 12, 0, 20)
            text = "Mencari video di penyimpanan TV dan USB..."
        }
        listView = ListView(this).apply {
            divider = GradientDrawable().apply { setColor(Color.rgb(35, 48, 60)) }
            dividerHeight = 1
            setBackgroundColor(Color.rgb(18, 29, 40))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
            )
        }
        pickButton = Button(this).apply {
            text = "PILIH DARI APLIKASI LAIN"
            textSize = 16f
            isAllCaps = false
            setOnClickListener { openSystemPicker() }
        }
        root.addView(title)
        root.addView(status)
        root.addView(listView)
        root.addView(pickButton, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = 20 })
        listView.setOnItemClickListener { _, _, position, _ ->
            val item = videos.getOrNull(position) ?: return@setOnItemClickListener
            copyVideo(item.uri)
        }
        return root
    }

    private fun hasPermission(): Boolean {
        val perm = if (Build.VERSION.SDK_INT >= 33) {
            Manifest.permission.READ_MEDIA_VIDEO
        } else {
            Manifest.permission.READ_EXTERNAL_STORAGE
        }
        return checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestPermission() {
        val perm = if (Build.VERSION.SDK_INT >= 33) {
            Manifest.permission.READ_MEDIA_VIDEO
        } else {
            Manifest.permission.READ_EXTERNAL_STORAGE
        }
        requestPermissions(arrayOf(perm), REQ_PERMISSION)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_PERMISSION) return
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            loadVideos()
        } else {
            status.text = "Izin penyimpanan ditolak. Pakai tombol di bawah untuk memilih video."
        }
    }

    private fun loadVideos() {
        status.text = "Mencari video..."
        videos.clear()
        try {
            val uris = mutableListOf<Uri>()
            if (Build.VERSION.SDK_INT >= 29) {
                for (volume in MediaStore.getExternalVolumeNames(this)) {
                    uris.add(MediaStore.Video.Media.getContentUri(volume))
                }
            } else {
                uris.add(MediaStore.Video.Media.EXTERNAL_CONTENT_URI)
            }
            val projection = arrayOf(
                MediaStore.Video.Media._ID,
                MediaStore.Video.Media.DISPLAY_NAME,
                MediaStore.Video.Media.SIZE,
            )
            for (base in uris.distinct()) {
                try {
                    contentResolver.query(
                        base, projection, null, null,
                        "${MediaStore.Video.Media.DATE_ADDED} DESC"
                    )?.use { c ->
                        val idCol = c.getColumnIndexOrThrow(MediaStore.Video.Media._ID)
                        val nameCol = c.getColumnIndexOrThrow(MediaStore.Video.Media.DISPLAY_NAME)
                        val sizeCol = c.getColumnIndexOrThrow(MediaStore.Video.Media.SIZE)
                        while (c.moveToNext()) {
                            val id = c.getLong(idCol)
                            val name = c.getString(nameCol) ?: "video"
                            val size = c.getLong(sizeCol)
                            val uri = ContentUris.withAppendedId(base, id)
                            if (videos.none { it.uri == uri }) {
                                videos.add(VideoItem(uri, name, size))
                            }
                        }
                    }
                } catch (_: Exception) {
                }
            }
        } catch (e: Exception) {
            status.text = "Gagal membaca penyimpanan: ${e.message}"
        }
        if (videos.isEmpty()) {
            status.text = "Tidak ada video terbaca. Colokkan USB, atau pilih lewat aplikasi lain."
            listView.adapter = null
            pickButton.requestFocus()
            return
        }
        status.text = "${videos.size} video ditemukan. Pilih dengan tombol OK remote."
        val labels = videos.map { "${it.name}\n${formatSize(it.size)}" }
        listView.adapter = object : ArrayAdapter<String>(this, android.R.layout.simple_list_item_1, labels) {
            override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
                val v = super.getView(position, convertView, parent) as TextView
                v.setTextColor(Color.WHITE)
                v.textSize = 18f
                v.setPadding(24, 18, 24, 18)
                v.gravity = Gravity.CENTER_VERTICAL
                return v
            }
        }
        listView.requestFocus()
    }

    private fun openSystemPicker() {
        try {
            val i = Intent(Intent.ACTION_GET_CONTENT).apply {
                type = "video/*"
                addCategory(Intent.CATEGORY_OPENABLE)
            }
            startActivityForResult(Intent.createChooser(i, "Pilih video"), REQ_PICK)
        } catch (e: Exception) {
            status.text = "Tidak ada aplikasi pemilih video: ${e.message}"
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_PICK && resultCode == RESULT_OK) {
            data?.data?.let { copyVideo(it) }
        }
    }

    private fun copyVideo(uri: Uri) {
        val name = if (mediaType == "lockscreen") "lockscreen.mp4" else "promo.mp4"
        status.text = "Menyalin $name..."
        pickButton.isEnabled = false
        Thread {
            var ok = false
            var error = ""
            try {
                val target = Prefs.mediaFile(this, name)
                target.parentFile?.mkdirs()
                val tmp = File(target.parentFile, ".$name.part")
                contentResolver.openInputStream(uri)?.use { input ->
                    tmp.outputStream().use { output ->
                        input.copyTo(output, 128 * 1024)
                    }
                } ?: throw IllegalStateException("file tidak bisa dibuka")
                if (tmp.length() <= 0L) throw IllegalStateException("file kosong")
                if (!tmp.renameTo(target)) {
                    tmp.copyTo(target, overwrite = true)
                    tmp.delete()
                }
                ok = true
            } catch (e: Exception) {
                error = e.message ?: "gagal menyalin"
            }
            runOnUiThread {
                pickButton.isEnabled = true
                if (ok) {
                    status.text = "$name berhasil disimpan."
                    TvOverlayService.instance?.onMediaPicked(name, mediaType)
                    finish()
                } else {
                    status.text = "Gagal menyalin: $error"
                }
            }
        }.start()
    }

    private fun formatSize(bytes: Long): String {
        if (bytes <= 0) return "-"
        val mb = bytes / (1024.0 * 1024.0)
        return if (mb >= 1) String.format("%.1f MB", mb) else "${bytes / 1024} KB"
    }

    companion object {
        private const val EXTRA_TYPE = "media_type"
        private const val REQ_PERMISSION = 41
        private const val REQ_PICK = 42

        fun start(context: Context, mediaType: String) {
            val i = Intent(context, MediaPickerActivity::class.java)
                .putExtra(EXTRA_TYPE, mediaType)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(i)
        }
    }
}
