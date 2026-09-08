class CustomerTransaction {
  final String id;
  final String owner;
  final String customerId;
  final String jenis;
  final String deskripsi;
  final int jumlahMenit;
  final int nominal;
  final String ref;
  final String createdAt;

  CustomerTransaction({
    required this.id,
    required this.owner,
    required this.customerId,
    required this.jenis,
    required this.deskripsi,
    this.jumlahMenit = 0,
    this.nominal = 0,
    this.ref = '',
    this.createdAt = '',
  });

  factory CustomerTransaction.fromJson(Map<String, dynamic> json) {
    return CustomerTransaction(
      id: json['id'] ?? '',
      owner: json['owner'] ?? '',
      customerId: json['customer_id'] ?? '',
      jenis: json['jenis'] ?? 'topup',
      deskripsi: json['deskripsi'] ?? '',
      jumlahMenit: json['jumlah_menit'] ?? 0,
      nominal: json['nominal'] ?? 0,
      ref: json['ref'] ?? '',
      createdAt: json['created_at'] ?? '',
    );
  }

  String get jenisLabel {
    switch (jenis) {
      case 'booking':
        return 'Booking';
      case 'order':
        return 'Order F&B';
      case 'topup':
        return 'Top Up';
      default:
        return jenis;
    }
  }
}