class ApiConfig {
  // Ganti dengan IP komputer yang menjalankan server.py
  // Untuk emulator Android: 10.0.2.2 (merujuk ke host PC)
  // Untuk device physical: IP lokal komputer (contoh: 192.168.1.x)
  // Catatan: pakai IP ini jika mengakses dari jaringan berbeda (rumah/outside)
  // Jika localhost/melayani di komputer sama saja gunakan http://10.0.2.2:8000
  static const String baseUrl = 'http://10.0.2.2:8000';

  // Supabase (untuk realtime booking status)
  static const String supabaseUrl = 'https://nqaucjpbnewckedqcezb.supabase.co';
  static const String supabaseKey =
      'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5xYXVjanBibmV3Y2tlZHFjZXpiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1MjUyNzUsImV4cCI6MjEwNDEwMTI3NX0.xi-h-3E2Yww95HzXsNmmiOmdvMKi_TaFNw8Op7xryig';
}
