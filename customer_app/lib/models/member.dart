class MemberCard {
  final String id;
  final String jenis;
  final String nama;
  final String noHp;
  final int saldoMenit;
  final String status;
  final String createdAt;

  MemberCard({
    required this.id,
    required this.jenis,
    required this.nama,
    this.noHp = '',
    this.saldoMenit = 0,
    this.status = 'aktif',
    this.createdAt = '',
  });

  factory MemberCard.fromJson(Map<String, dynamic> json) {
    return MemberCard(
      id: json['id'] ?? '',
      jenis: json['jenis'] ?? '',
      nama: json['nama'] ?? '',
      noHp: json['no_hp'] ?? '',
      saldoMenit: json['saldo_menit'] ?? 0,
      status: json['status'] ?? 'aktif',
      createdAt: json['created_at'] ?? '',
    );
  }
}

class MemberPaket {
  final String nama;
  final int menit;
  final int harga;

  MemberPaket({
    required this.nama,
    required this.menit,
    required this.harga,
  });

  factory MemberPaket.fromJson(Map<String, dynamic> json) {
    return MemberPaket(
      nama: json['nama'] ?? '',
      menit: json['menit'] ?? 0,
      harga: json['harga'] ?? 0,
    );
  }
}

class MemberPlans {
  final List<String> jenis;
  final Map<String, List<MemberPaket>> plans; // jenis -> [paket]

  MemberPlans({required this.jenis, required this.plans});

  factory MemberPlans.fromJson(Map<String, dynamic> json) {
    final jenis = (json['jenis'] as List? ?? []).cast<String>();
    final plans = <String, List<MemberPaket>>{};
    final rawPlans = json['plans'] as Map<String, dynamic>? ?? {};
    rawPlans.forEach((k, v) {
      plans[k] = (v as List? ?? [])
          .map((e) => MemberPaket.fromJson(e as Map<String, dynamic>))
          .toList();
    });
    return MemberPlans(jenis: jenis, plans: plans);
  }
}

class MemberTopup {
  final String id;
  final String jenis;
  final String paket;
  final int menit;
  final int harga;
  final String metode;
  final String status;
  final String alasan;
  final String createdAt;

  MemberTopup({
    required this.id,
    required this.jenis,
    required this.paket,
    this.menit = 0,
    this.harga = 0,
    this.metode = '',
    this.status = '',
    this.alasan = '',
    this.createdAt = '',
  });

  factory MemberTopup.fromJson(Map<String, dynamic> json) {
    return MemberTopup(
      id: json['id'] ?? '',
      jenis: json['jenis'] ?? '',
      paket: json['paket'] ?? '',
      menit: json['menit'] ?? 0,
      harga: json['harga'] ?? 0,
      metode: json['metode'] ?? '',
      status: json['status'] ?? '',
      alasan: json['alasan'] ?? '',
      createdAt: json['created_at'] ?? '',
    );
  }
}

class MemberTv {
  final String label;
  final String grup;

  MemberTv({required this.label, required this.grup});

  factory MemberTv.fromJson(Map<String, dynamic> json) {
    return MemberTv(
      label: json['label'] ?? '',
      grup: json['grup'] ?? '',
    );
  }
}

class MemberStartResult {
  final String label;
  final int sisaMenit;
  final String namaMember;

  MemberStartResult({
    required this.label,
    required this.sisaMenit,
    required this.namaMember,
  });

  factory MemberStartResult.fromJson(Map<String, dynamic> json) {
    return MemberStartResult(
      label: json['label'] ?? '',
      sisaMenit: json['sisa_menit'] ?? 0,
      namaMember: json['nama_member'] ?? '',
    );
  }
}

class MemberTvMap {
  final Map<String, List<MemberTv>> tvs; // grup -> [tv]

  MemberTvMap({required this.tvs});

  factory MemberTvMap.fromJson(Map<String, dynamic> json) {
    final tvs = <String, List<MemberTv>>{};
    final raw = json['tvs'] as Map<String, dynamic>? ?? {};
    raw.forEach((k, v) {
      tvs[k] = (v as List? ?? [])
          .map((e) => MemberTv.fromJson(e as Map<String, dynamic>))
          .toList();
    });
    return MemberTvMap(tvs: tvs);
  }
}