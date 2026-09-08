import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../models/booking.dart';

class RiwayatScreen extends StatefulWidget {
  const RiwayatScreen({super.key});

  @override
  State<RiwayatScreen> createState() => _RiwayatScreenState();
}

class _RiwayatScreenState extends State<RiwayatScreen> {
  final _api = ApiService();
  List<Booking> _bookings = [];
  bool _loading = true;
  String _filter = 'semua';

  @override
  void initState() {
    super.initState();
    _loadRiwayat();
  }

  Future<void> _loadRiwayat() async {
    setState(() => _loading = true);
    try {
      final resp = await _api.getRiwayat();
      final list = (resp['riwayat'] as List? ?? [])
          .map((b) => Booking.fromJson(b))
          .toList();
      setState(() {
        _bookings = list;
        _loading = false;
      });
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  List<Booking> get _filtered {
    if (_filter == 'semua') return _bookings;
    if (_filter == 'aktif') {
      return _bookings.where((b) => b.status == 'baru' || b.status == 'dikonfirmasi').toList();
    }
    return _bookings.where((b) => b.status == 'selesai').toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Riwayat Saya')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                _filterChip('Semua', 'semua'),
                const SizedBox(width: 8),
                _filterChip('Aktif', 'aktif'),
                const SizedBox(width: 8),
                _filterChip('Selesai', 'selesai'),
              ],
            ),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)))
                : _filtered.isEmpty
                    ? const Center(
                        child: Text('Belum ada riwayat',
                            style: TextStyle(color: Color(0xFF8B949E))),
                      )
                    : RefreshIndicator(
                        onRefresh: _loadRiwayat,
                        child: ListView.builder(
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          itemCount: _filtered.length,
                          itemBuilder: (ctx, i) => _bookingCard(_filtered[i]),
                        ),
                      ),
          ),
        ],
      ),
    );
  }

  Widget _filterChip(String label, String value) {
    final selected = _filter == value;
    return Expanded(
      child: GestureDetector(
        onTap: () => setState(() => _filter = value),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: selected ? const Color(0xFF00E676) : const Color(0xFF21262D),
            borderRadius: BorderRadius.circular(8),
          ),
          alignment: Alignment.center,
          child: Text(
            label,
            style: TextStyle(
              color: selected ? Colors.black : const Color(0xFFF0F6FC),
              fontWeight: FontWeight.w500,
              fontSize: 13,
            ),
          ),
        ),
      ),
    );
  }

  Widget _bookingCard(Booking b) {
    Color statusColor;
    switch (b.status) {
      case 'dikonfirmasi':
        statusColor = const Color(0xFF3FB950);
        break;
      case 'ditolak':
        statusColor = const Color(0xFFF85149);
        break;
      case 'selesai':
        statusColor = const Color(0xFF8B949E);
        break;
      default:
        statusColor = const Color(0xFFF78166);
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF161B22),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF21262D)),
      ),
      child: Row(
        children: [
          Container(
            width: 4,
            height: 40,
            decoration: BoxDecoration(
              color: statusColor,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${b.perangkat} | ${b.paket}',
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    color: Color(0xFFF0F6FC),
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '${b.tanggal} ${b.jam}',
                  style: const TextStyle(fontSize: 12, color: Color(0xFF8B949E)),
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                'Rp ${b.totalHarga}',
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  color: Color(0xFFF0F6FC),
                ),
              ),
              const SizedBox(height: 2),
              Text(
                b.statusLabel,
                style: TextStyle(fontSize: 12, color: statusColor),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
