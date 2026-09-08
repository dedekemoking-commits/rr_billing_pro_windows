import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../services/api_service.dart';
import '../models/customer.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _api = ApiService();
  Customer? _customer;
  List<Map<String, dynamic>> _promo = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    try {
      final results = await Future.wait([
        _api.getProfile(),
        _api.getPromo(),
      ]);
      if (!mounted) return;
      setState(() {
        _customer = Customer.fromJson(results[0]);
        _promo = List<Map<String, dynamic>>.from(results[1]['promo'] ?? []);
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_customer?.nama ?? 'RR Billing Pro'),
        actions: [
          IconButton(
            icon: const Icon(Icons.person_outline),
            onPressed: () => context.push('/profil'),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)))
          : RefreshIndicator(
              onRefresh: _loadData,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  // ── Saldo Card ──
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [Color(0xFF00E676), Color(0xFF00C853)],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Saldo Waktu',
                          style: TextStyle(
                            fontSize: 14,
                            color: Colors.black54,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '${_customer?.saldoWaktu ?? 0} Menit',
                          style: const TextStyle(
                            fontSize: 32,
                            fontWeight: FontWeight.bold,
                            color: Colors.black,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            _quickAction(
                              icon: Icons.add_circle_outline,
                              label: 'Top Up',
                              onTap: () => context.push('/topup'),
                            ),
                            const SizedBox(width: 16),
                            _quickAction(
                              icon: Icons.history,
                              label: 'Riwayat',
                              onTap: () => context.push('/riwayat'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),

                  // ── Booking Button ──
                  SizedBox(
                    height: 56,
                    child: ElevatedButton.icon(
                      onPressed: () => context.push('/booking'),
                      icon: const Icon(Icons.calendar_today, color: Colors.black),
                      label: const Text('Booking Sekarang',
                          style: TextStyle(color: Colors.black)),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFF78166),
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),

                  // ── Member Card ──
                  GestureDetector(
                    onTap: () => context.push('/member'),
                    child: Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          colors: [Color(0xFF3FB950), Color(0xFF00C853)],
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                        ),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.credit_card,
                              color: Colors.black, size: 32),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: const [
                                Text(
                                  'Member Saya',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                    color: Colors.black,
                                  ),
                                ),
                                Text(
                                  'Daftar, isi waktu, & nyalakan TV langsung dari HP',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: Colors.black54,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const Icon(Icons.chevron_right, color: Colors.black),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),

                  // ── Promo ──
                  if (_promo.isNotEmpty) ...[
                    const Text(
                      'Promo Hari Ini',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFFF0F6FC),
                      ),
                    ),
                    const SizedBox(height: 12),
                    ..._promo.map((p) => Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: const Color(0xFF161B22),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(color: const Color(0xFF21262D)),
                          ),
                          child: Row(
                            children: [
                              const Icon(Icons.local_offer,
                                  color: Color(0xFFF78166), size: 28),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      p['judul'] ?? '',
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w600,
                                        color: Color(0xFFF0F6FC),
                                      ),
                                    ),
                                    Text(
                                      p['deskripsi'] ?? '',
                                      style: const TextStyle(
                                        fontSize: 12,
                                        color: Color(0xFF8B949E),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        )),
                  ],

                  // ── Menu Grid ──
                  const SizedBox(height: 12),
                  const Text(
                    'Menu',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFFF0F6FC),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      _menuCard(
                        icon: Icons.receipt_long,
                        label: 'Riwayat',
                        color: const Color(0xFF58A6FF),
                        onTap: () => context.push('/riwayat'),
                      ),
                      const SizedBox(width: 12),
                      _menuCard(
                        icon: Icons.history,
                        label: 'Transaksi',
                        color: const Color(0xFF00E676),
                        onTap: () => context.push('/transaksi'),
                      ),
                      const SizedBox(width: 12),
                      _menuCard(
                        icon: Icons.restaurant,
                        label: 'Menu F&B',
                        color: const Color(0xFF3FB950),
                        onTap: () => context.push('/menu'),
                      ),
                      const SizedBox(width: 12),
                      _menuCard(
                        icon: Icons.card_giftcard,
                        label: 'Voucher',
                        color: const Color(0xFFF78166),
                        onTap: () => context.push('/voucher'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
    );
  }

  Widget _quickAction({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
  }) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        decoration: BoxDecoration(
          color: Colors.black.withOpacity(0.2),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(
          children: [
            Icon(icon, size: 18, color: Colors.black),
            const SizedBox(width: 6),
            Text(label, style: const TextStyle(color: Colors.black, fontSize: 13)),
          ],
        ),
      ),
    );
  }

  Widget _menuCard({
    required IconData icon,
    required String label,
    required Color color,
    required VoidCallback onTap,
  }) {
    return Expanded(
      child: GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 20),
          decoration: BoxDecoration(
            color: const Color(0xFF161B22),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFF21262D)),
          ),
          child: Column(
            children: [
              Icon(icon, color: color, size: 28),
              const SizedBox(height: 8),
              Text(
                label,
                style: const TextStyle(
                  fontSize: 12,
                  color: Color(0xFFF0F6FC),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
