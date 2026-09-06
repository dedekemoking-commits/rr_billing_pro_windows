import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../services/api_service.dart';
import '../../services/auth_service.dart';
import '../../models/customer.dart';

class ProfilScreen extends StatefulWidget {
  const ProfilScreen({super.key});

  @override
  State<ProfilScreen> createState() => _ProfilScreenState();
}

class _ProfilScreenState extends State<ProfilScreen> {
  final _api = ApiService();
  final _auth = AuthService();
  Customer? _customer;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadProfile();
  }

  Future<void> _loadProfile() async {
    try {
      final resp = await _api.getProfile();
      setState(() {
        _customer = Customer.fromJson(resp);
        _loading = false;
      });
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Profil')),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // ── Avatar ──
                Center(
                  child: Container(
                    width: 80,
                    height: 80,
                    decoration: BoxDecoration(
                      color: const Color(0xFF21262D),
                      shape: BoxShape.circle,
                    ),
                    child: _customer?.avatarUrl != null &&
                            _customer!.avatarUrl.isNotEmpty
                        ? ClipOval(
                            child: Image.network(
                              _customer!.avatarUrl,
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => const Icon(
                                Icons.person,
                                size: 40,
                                color: Color(0xFF8B949E),
                              ),
                            ),
                          )
                        : const Icon(Icons.person, size: 40, color: Color(0xFF8B949E)),
                  ),
                ),
                const SizedBox(height: 16),
                Center(
                  child: Text(
                    _customer?.nama ?? '-',
                    style: const TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFFF0F6FC),
                    ),
                  ),
                ),
                Center(
                  child: Text(
                    _customer?.email ?? '-',
                    style: const TextStyle(color: Color(0xFF8B949E), fontSize: 14),
                  ),
                ),
                const SizedBox(height: 24),

                // ── Info ──
                _infoTile(Icons.store, 'Rental', _api.owner ?? '-'),
                _infoTile(Icons.access_time, 'Saldo', '${_customer?.saldoWaktu ?? 0} Menit'),
                _infoTile(Icons.calendar_today, 'Terdaftar', _customer?.createdAt ?? '-'),

                const SizedBox(height: 24),

                // ── Logout ──
                OutlinedButton.icon(
                  onPressed: () async {
                    final confirm = await showDialog<bool>(
                      context: context,
                      builder: (ctx) => AlertDialog(
                        backgroundColor: const Color(0xFF161B22),
                        title: const Text('Keluar?',
                            style: TextStyle(color: Color(0xFFF0F6FC))),
                        content: const Text('Anda akan keluar dari akun ini.',
                            style: TextStyle(color: Color(0xFF8B949E))),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(ctx, false),
                            child: const Text('Batal',
                                style: TextStyle(color: Color(0xFF8B949E))),
                          ),
                          TextButton(
                            onPressed: () => Navigator.pop(ctx, true),
                            child: const Text('Keluar',
                                style: TextStyle(color: Color(0xFFF85149))),
                          ),
                        ],
                      ),
                    );
                    if (confirm == true) {
                      await _auth.signOut();
                      if (!mounted) return;
                      context.go('/kode-rental');
                    }
                  },
                  icon: const Icon(Icons.logout, color: Color(0xFFF85149)),
                  label: const Text('Keluar',
                      style: TextStyle(color: Color(0xFFF85149))),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: Color(0xFFF85149)),
                    minimumSize: const Size(double.infinity, 50),
                  ),
                ),
              ],
            ),
    );
  }

  Widget _infoTile(IconData icon, String label, String value) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF161B22),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Icon(icon, color: const Color(0xFF8B949E), size: 20),
          const SizedBox(width: 12),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label,
                  style: const TextStyle(fontSize: 12, color: Color(0xFF8B949E))),
              Text(value,
                  style: const TextStyle(color: Color(0xFFF0F6FC))),
            ],
          ),
        ],
      ),
    );
  }
}
