import 'package:flutter/material.dart';
import '../../services/api_service.dart';

class VoucherScreen extends StatefulWidget {
  const VoucherScreen({super.key});

  @override
  State<VoucherScreen> createState() => _VoucherScreenState();
}

class _VoucherScreenState extends State<VoucherScreen> {
  final _controller = TextEditingController();
  final _api = ApiService();
  bool _loading = false;

  Future<void> _redeem() async {
    final kode = _controller.text.trim();
    if (kode.isEmpty) return;
    setState(() => _loading = true);
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
      if (resp['ok'] == true) _controller.clear();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error: $e')),
      );
    }
    setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Voucher')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: const Color(0xFF161B22),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Column(
                children: [
                  Icon(Icons.card_giftcard, color: Color(0xFFF78166), size: 48),
                  SizedBox(height: 12),
                  Text(
                    'Pakai Voucher',
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFFF0F6FC),
                    ),
                  ),
                  SizedBox(height: 4),
                  Text(
                    'Masukkan kode voucher dari kasir',
                    style: TextStyle(color: Color(0xFF8B949E), fontSize: 13),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),
            TextField(
              controller: _controller,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                hintText: 'Kode voucher',
                prefixIcon: const Icon(Icons.code, color: Color(0xFF8B949E)),
                suffixIcon: _loading
                    ? const Padding(
                        padding: EdgeInsets.all(12),
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : null,
              ),
              onSubmitted: (_) => _redeem(),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loading ? null : _redeem,
              child: const Text('Redeem Voucher'),
            ),
          ],
        ),
      ),
    );
  }
}
