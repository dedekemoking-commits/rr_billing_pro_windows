class Promo {
  final String id;
  final String judul;
  final String deskripsi;
  final String gambarUrl;
  final String jenis;
  final int nilai;
  final String berlakuDari;
  final String berlakuSampai;

  Promo({
    required this.id,
    required this.judul,
    required this.deskripsi,
    this.gambarUrl = '',
    required this.jenis,
    required this.nilai,
    required this.berlakuDari,
    required this.berlakuSampai,
  });

  factory Promo.fromJson(Map<String, dynamic> json) {
    return Promo(
      id: json['id'] ?? '',
      judul: json['judul'] ?? '',
      deskripsi: json['deskripsi'] ?? '',
      gambarUrl: json['gambar_url'] ?? '',
      jenis: json['jenis'] ?? '',
      nilai: json['nilai'] ?? 0,
      berlakuDari: json['berlaku_dari'] ?? '',
      berlakuSampai: json['berlaku_sampai'] ?? '',
    );
  }
}

class MenuItem {
  final String nama;
  final int harga;

  MenuItem({required this.nama, required this.harga});

  factory MenuItem.fromEntry(String nama, dynamic harga) {
    return MenuItem(nama: nama, harga: int.tryParse(harga.toString()) ?? 0);
  }
}
