import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../services/api_service.dart';

class KodeRentalScreen extends StatefulWidget {
  const KodeRentalScreen({super.key});

  @override
  State<KodeRentalScreen> createState() => _KodeRentalScreenState();
}

class _KodeRentalScreenState extends State<KodeRentalScreen> {
  final _controller = TextEditingController();
  final _api = ApiService();
  bool _loading = false;
  String? _error;
  Map<String, dynamic>? _rentalInfo;

  Future<void> _cekRental() async {
    final kode = _controller.text.trim();
    if (kode.isEmpty) {
      setState(() => _error = 'Masukkan kode rental');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
      _rentalInfo = null;
    });
    try {
      final resp = await _api.cekRental(kode);
      if (resp['ok'] == true) {
        setState(() {
          _rentalInfo = resp;
          _loading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = 'Rental tidak ditemukan';
        _loading = false;
      });
    }
  }

  void _lanjutkan() {
    if (_rentalInfo != null) {
      final owner = _rentalInfo!['owner'] ?? _controller.text.trim();
      context.go('/login', extra: owner);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 40),
              const Icon(
                Icons.store,
                size: 64,
                color: Color(0xFF00E676),
              ),
              const SizedBox(height: 16),
              const Text(
                'Masukkan Kode Rental',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFF0F6FC),
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Minta kode rental kepada kasir',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 14,
                  color: Color(0xFF8B949E),
                ),
              ),
              const SizedBox(height: 32),
              TextField(
                controller: _controller,
                textCapitalization: TextCapitalization.none,
                decoration: InputDecoration(
                  hintText: 'Contoh: rrbillingpro',
                  prefixIcon: const Icon(Icons.code, color: Color(0xFF8B949E)),
                  suffixIcon: _loading
                      ? const Padding(
                          padding: EdgeInsets.all(12),
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : IconButton(
                          icon: const Icon(Icons.arrow_forward,
                              color: Color(0xFF00E676)),
                          onPressed: _cekRental,
                        ),
                ),
                onSubmitted: (_) => _cekRental(),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(
                  _error!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Color(0xFFF85149), fontSize: 13),
                ),
              ],
              if (_rentalInfo != null) ...[
                const SizedBox(height: 24),
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: const Color(0xFF161B22),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: const Color(0xFF00E676), width: 1),
                  ),
                  child: Column(
                    children: [
                      const Icon(Icons.check_circle,
                          color: Color(0xFF3FB950), size: 32),
                      const SizedBox(height: 8),
                      Text(
                        _rentalInfo!['nama_rental'] ?? '',
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                          color: Color(0xFFF0F6FC),
                        ),
                      ),
                      if (_rentalInfo!['alamat'] != null &&
                          _rentalInfo!['alamat'].toString().isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(
                          _rentalInfo!['alamat'],
                          style: const TextStyle(
                            fontSize: 13,
                            color: Color(0xFF8B949E),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: _lanjutkan,
                  child: const Text('Lanjutkan'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
