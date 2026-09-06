import 'package:flutter/material.dart';
import '../../services/api_service.dart';

class TopUpScreen extends StatefulWidget {
  const TopUpScreen({super.key});

  @override
  State<TopUpScreen> createState() => _TopUpScreenState();
}

class _TopUpScreenState extends State<TopUpScreen> {
  final _api = ApiService();
  int _saldo = 0;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadSaldo();
  }

  Future<void> _loadSaldo() async {
    try {
      final resp = await _api.getSaldo();
      setState(() {
        _saldo = resp['saldo_waktu'] ?? 0;
        _loading = false;
      });
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Saldo & Top Up')),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Container(
                  padding: const EdgeInsets.all(24),
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(
                      colors: [Color(0xFF00E676), Color(0xFF00C853)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Column(
                    children: [
                      const Text('Saldo Waktu Anda',
                          style: TextStyle(color: Colors.black54, fontSize: 14)),
                      const SizedBox(height: 4),
                      Text(
                        '$_saldo Menit',
                        style: const TextStyle(
                          fontSize: 40,
                          fontWeight: FontWeight.bold,
                          color: Colors.black,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                const Text('Top Up via Voucher',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFFF0F6FC),
                    )),
                const SizedBox(height: 12),
                const Text(
                  'Minta kode voucher kepada kasir, lalu masukkan di bawah.',
                  style: TextStyle(color: Color(0xFF8B949E), fontSize: 13),
                ),
                const SizedBox(height: 12),
                ElevatedButton(
                  onPressed: () => _showVoucherDialog(),
                  child: const Text('Masukkan Kode Voucher'),
                ),
              ],
            ),
    );
  }

  void _showVoucherDialog() {
    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF161B22),
        title: const Text('Kode Voucher', style: TextStyle(color: Color(0xFFF0F6FC))),
        content: TextField(
          controller: controller,
          textCapitalization: TextCapitalization.characters,
          decoration: const InputDecoration(hintText: 'Masukkan kode voucher'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Batal', style: TextStyle(color: Color(0xFF8B949E))),
          ),
          TextButton(
            onPressed: () async {
              Navigator.pop(ctx);
              final kode = controller.text.trim();
              if (kode.isEmpty) return;
              try {
                final resp = await _api.redeemVoucher(kode);
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(resp['pesan'] ?? resp['error'] ?? 'Selesai'),
                    backgroundColor: resp['ok'] == true
                        ? const Color(0xFF3FB950)
                        : const Color(0xFFF85149),
                  ),
                );
                _loadSaldo();
              } catch (e) {
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Error: $e')),
                );
              }
            },
            child: const Text('Redeem', style: TextStyle(color: Color(0xFF00E676))),
          ),
        ],
      ),
    );
  }
}
