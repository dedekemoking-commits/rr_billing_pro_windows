import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../models/transaction.dart';

class TransaksiScreen extends StatefulWidget {
  const TransaksiScreen({super.key});

  @override
  State<TransaksiScreen> createState() => _TransaksiScreenState();
}

class _TransaksiScreenState extends State<TransaksiScreen> {
  final _api = ApiService();
  List<CustomerTransaction> _trans = [];
  bool _loading = true;
  String _filter = 'semua';

  @override
  void initState() {
    super.initState();
    _loadTransaksi();
  }

  Future<void> _loadTransaksi() async {
    setState(() => _loading = true);
    try {
      final resp = await _api.getTransaksi();
      final list = (resp['transaksi'] as List? ?? [])
          .map((t) => CustomerTransaction.fromJson(t))
          .toList();
      setState(() {
        _trans = list;
        _loading = false;
      });
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  List<CustomerTransaction> get _filtered {
    if (_filter == 'semua') return _trans;
    return _trans.where((t) => t.jenis == _filter).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Riwayat Pembelian')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                _filterChip('Semua', 'semua'),
                const SizedBox(width: 8),
                _filterChip('Top Up', 'topup'),
                const SizedBox(width: 8),
                _filterChip('Booking', 'booking'),
                const SizedBox(width: 8),
                _filterChip('F&B', 'order'),
              ],
            ),
          ),
          Expanded(
            child: _loading
                ? const Center(
                    child: CircularProgressIndicator(color: Color(0xFF00E676)))
                : _filtered.isEmpty
                    ? const Center(
                        child: Text('Belum ada transaksi',
                            style: TextStyle(color: Color(0xFF8B949E))),
                      )
                    : RefreshIndicator(
                        onRefresh: _loadTransaksi,
                        child: ListView.builder(
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          itemCount: _filtered.length,
                          itemBuilder: (ctx, i) => _transCard(_filtered[i]),
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
              fontSize: 12,
            ),
          ),
        ),
      ),
    );
  }

  (IconData, Color) _jenisVisual(String jenis) {
    switch (jenis) {
      case 'topup':
        return (Icons.add_circle, const Color(0xFF3FB950));
      case 'booking':
        return (Icons.calendar_today, const Color(0xFF58A6FF));
      case 'order':
        return (Icons.restaurant, const Color(0xFFF78166));
      default:
        return (Icons.receipt_long, const Color(0xFF8B949E));
    }
  }

  Widget _transCard(CustomerTransaction t) {
    final (icon, color) = _jenisVisual(t.jenis);
    final dateStr = _formatTanggal(t.createdAt);
    final nominalStr = t.nominal > 0
        ? 'Rp ${_formatNum(t.nominal)}'
        : (t.jumlahMenit > 0 ? '+${t.jumlahMenit} menit' : null);

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
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: color.withOpacity(0.15),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, color: color, size: 22),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  t.deskripsi,
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    color: Color(0xFFF0F6FC),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  '${t.jenisLabel} • $dateStr',
                  style: const TextStyle(fontSize: 12, color: Color(0xFF8B949E)),
                ),
              ],
            ),
          ),
          if (nominalStr != null)
            Text(
              nominalStr,
              style: TextStyle(
                fontWeight: FontWeight.w600,
                color: t.jenis == 'topup' ? const Color(0xFF3FB950) : const Color(0xFFF0F6FC),
              ),
            ),
        ],
      ),
    );
  }

  String _formatNum(int n) {
    final s = n.toString();
    final buf = StringBuffer();
    for (int i = 0; i < s.length; i++) {
      if (i > 0 && (s.length - i) % 3 == 0) buf.write('.');
      buf.write(s[i]);
    }
    return buf.toString();
  }

  String _formatTanggal(String iso) {
    if (iso.isEmpty) return '';
    // format: 2026-09-08T03:15:00 ...
    final t = iso.replaceFirst('T', ' ').substring(0, iso.contains('T') ? 19 : iso.length);
    return t;
  }
}