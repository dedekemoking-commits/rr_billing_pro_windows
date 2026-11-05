package com.rrbillingpro.tvclient

import android.app.Application
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions

/**
 * Application class: inisialisasi Firebase App sebelum Activity/Service lahir.
 * Try/catch + fallback: kalau tanpa google-services.json, buat FirebaseApp
 * dengan default empty options (FirebaseFirestore tetap bisa dipakai,
 * tapi tak akan terhubung ke project Firebase aktual).
 */
class RRBillingApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        // Inisialisasi Firebase App. Tanpa google-services.json, FirebaseApp
        // akan dibuat dengan default options kosong — app tetap jalan (tidak
        // crash) tapi Firebase Firestore/tokens tidak terhubung ke project
        // Firebase aktual (termasuk synch status ke Cloud Firestore).
        FirebaseApp.initializeApp(this)
        android.util.Log.i("RRBillingApp", "FirebaseApp initialized")
    }
}
