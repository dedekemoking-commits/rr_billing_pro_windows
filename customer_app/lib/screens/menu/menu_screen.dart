import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../models/promo.dart';

class MenuScreen extends StatefulWidget {
  const MenuScreen({super.key});

  @override
  State<MenuScreen> createState() => _MenuScreenState();
}

class _MenuScreenState extends State<MenuScreen> {
  final _api = ApiService();
  List<MenuItem> _makanan = [];
  List<MenuItem> _minuman = [];
  final Map<String, int> _keranjang = {};
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadMenu();
  }

  Future<void> _loadMenu() async {
    try {
      final resp = await _api.getMenu();
      final makanan = (resp['makanan'] as Map<String, dynamic>? ?? {})
          .entries
          .map((e) => MenuItem.fromEntry(e.key, e.value))
          .toList();
      final minuman = (resp['minuman'] as Map<String, dynamic>? ?? {})
          .entries
          .map((e) => MenuItem.fromEntry(e.key, e.value))
          .toList();
      setState(() {
        _makanan = makanan;
        _minuman = minuman;
        _loading = false;
      });
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  int get _totalHarga {
    int total = 0;
    for (final entry in _keranjang.entries) {
      final item = [..._makanan, ..._minuman].firstWhere(
        (m) => m.nama == entry.key,
        orElse: () => MenuItem(nama: '', harga: 0),
      );
      total += item.harga * entry.value;
    }
    return total;
  }

  Future<void> _order() async {
    if (_keranjang.isEmpty) return;
    final items = _keranjang.entries.map((e) => {
      'nama': e.key,
      'qty': e.value,
      'harga': [..._makanan, ..._minuman]
          .firstWhere((m) => m.nama == e.key, orElse: () => MenuItem(nama: '', harga: 0))
          .harga,
    }).toList();
    try {
      final resp = await _api.createOrder(items, '');
      if (!mounted) return;
      if (resp['ok'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Order berhasil! Kasir akan segera mengirim.'),
            backgroundColor: Color(0xFF3FB950),
          ),
        );
        setState(() => _keranjang.clear());
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Menu F&B'),
        actions: [
          if (_keranjang.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Center(
                child: Text(
                  '${_keranjang.length} item',
                  style: const TextStyle(color: Color(0xFF00E676)),
                ),
              ),
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_makanan.isNotEmpty) ...[
                  const Text('Makanan',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFFF0F6FC),
                      )),
                  const SizedBox(height: 8),
                  ..._makanan.map((m) => _menuCard(m)),
                ],
                if (_minuman.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  const Text('Minuman',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFFF0F6FC),
                      )),
                  const SizedBox(height: 8),
                  ..._minuman.map((m) => _menuCard(m)),
                ],
              ],
            ),
      bottomNavigationBar: _keranjang.isNotEmpty
          ? Container(
              padding: const EdgeInsets.all(16),
              decoration: const BoxDecoration(
                color: Color(0xFF161B22),
                border: Border(top: BorderSide(color: Color(0xFF21262D))),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      'Total: Rp $_totalHarga',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFFF0F6FC),
                      ),
                    ),
                  ),
                  ElevatedButton(
                    onPressed: _order,
                    child: const Text('Pesan'),
                  ),
                ],
              ),
            )
          : null,
    );
  }

  Widget _menuCard(MenuItem item) {
    final qty = _keranjang[item.nama] ?? 0;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF161B22),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.nama,
                    style: const TextStyle(color: Color(0xFFF0F6FC), fontWeight: FontWeight.w500)),
                Text('Rp ${item.harga}',
                    style: const TextStyle(fontSize: 13, color: Color(0xFF8B949E))),
              ],
            ),
          ),
          if (qty > 0) ...[
            IconButton(
              iconSize: 20,
              icon: const Icon(Icons.remove_circle_outline, color: Color(0xFFF85149)),
              onPressed: () {
                setState(() {
                  if (qty <= 1) {
                    _keranjang.remove(item.nama);
                  } else {
                    _keranjang[item.nama] = qty - 1;
                  }
                });
              },
            ),
            Text('$qty', style: const TextStyle(color: Color(0xFFF0F6FC))),
          ],
          IconButton(
            iconSize: 20,
            icon: Icon(
              qty > 0 ? Icons.add_circle : Icons.add_circle_outline,
              color: const Color(0xFF00E676),
            ),
            onPressed: () {
              setState(() {
                _keranjang[item.nama] = qty + 1;
              });
            },
          ),
        ],
      ),
    );
  }
}
