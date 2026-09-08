class Booking {
  final String id;
  final String owner;
  final String namaPelanggan;
  final String perangkat;
  final String grup;
  final String paket;
  final int totalHarga;
  final String tanggal;
  final String jam;
  final String metode;
  final String statusBayar;
  final String status;
  final String catatan;
  final String createdAt;

  Booking({
    required this.id,
    required this.owner,
    required this.namaPelanggan,
    required this.perangkat,
    required this.grup,
    required this.paket,
    required this.totalHarga,
    required this.tanggal,
    required this.jam,
    required this.metode,
    required this.statusBayar,
    required this.status,
    this.catatan = '',
    this.createdAt = '',
  });

  factory Booking.fromJson(Map<String, dynamic> json) {
    return Booking(
      id: json['id'] ?? json['_id'] ?? '',
      owner: json['owner'] ?? '',
      namaPelanggan: json['namaPelanggan'] ?? '',
      perangkat: json['perangkat'] ?? '',
      grup: json['grup'] ?? '',
      paket: json['paket'] ?? '',
      totalHarga: json['totalHarga'] ?? 0,
      tanggal: json['tanggal'] ?? '',
      jam: json['jam'] ?? '',
      metode: json['metode'] ?? 'biasa',
      statusBayar: json['statusBayar'] ?? 'belum_bayar',
      status: json['status'] ?? 'baru',
      catatan: json['catatan'] ?? '',
      createdAt: json['createdAt'] ?? '',
    );
  }

  String get statusLabel {
    switch (status) {
      case 'baru':
        return 'Menunggu';
      case 'dikonfirmasi':
        return 'Dikonfirmasi';
      case 'ditolak':
        return 'Ditolak';
      case 'selesai':
        return 'Selesai';
      default:
        return status;
    }
  }
}
