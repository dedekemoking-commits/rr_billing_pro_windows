class Customer {
  final String id;
  final String nama;
  final String email;
  final String avatarUrl;
  final int saldoWaktu;

  Customer({
    required this.id,
    required this.nama,
    required this.email,
    this.avatarUrl = '',
    this.saldoWaktu = 0,
  });

  factory Customer.fromJson(Map<String, dynamic> json) {
    return Customer(
      id: json['id'] ?? '',
      nama: json['nama'] ?? '',
      email: json['email'] ?? '',
      avatarUrl: json['avatar_url'] ?? '',
      saldoWaktu: json['saldo_waktu'] ?? 0,
    );
  }
}

class RentalInfo {
  final String owner;
  final String namaRental;
  final String logo;
  final String noHp;
  final String alamat;

  RentalInfo({
    required this.owner,
    required this.namaRental,
    this.logo = '',
    this.noHp = '',
    this.alamat = '',
  });

  factory RentalInfo.fromJson(Map<String, dynamic> json) {
    return RentalInfo(
      owner: json['owner'] ?? '',
      namaRental: json['nama_rental'] ?? '',
      logo: json['logo'] ?? '',
      noHp: json['no_hp'] ?? '',
      alamat: json['alamat'] ?? '',
    );
  }
}
