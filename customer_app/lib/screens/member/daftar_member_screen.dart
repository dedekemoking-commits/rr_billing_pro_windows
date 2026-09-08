import 'package:flutter/material.dart';
import 'package:fluttertoast/fluttertoast.dart';
import '../../services/api_service.dart';
import '../../models/member.dart';

class DaftarMemberScreen extends StatefulWidget {
  const DaftarMemberScreen({super.key});

  @override
  State<DaftarMemberScreen> createState() => _DaftarMemberScreenState();
}

class _DaftarMemberScreenState extends State<DaftarMemberScreen> {
  final _api = ApiService();
  final _namaCtrl = TextEditingController();
  final _hpCtrl = TextEditingController();
  final _pinCtrl = TextEditingController();
  List<String> _jenis = [];
  String? _selectedJenis;
  bool _loading = true;
  bool _submitting = false;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _loadPlans();
  }

  @override
  void dispose() {
    _namaCtrl.dispose();
    _hpCtrl.dispose();
    _pinCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadPlans() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final resp = await _api.getMemberPlans();
      final plans = MemberPlans.fromJson(resp);
      if (!mounted) return;
      setState(() {
        _jenis = plans.jenis;
        _selectedJenis = _jenis.isNotEmpty ? _jenis.first : null;
        _error = _jenis.isEmpty
            ? 'Server tidak mengirim daftar jenis member.'
            : '';
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Gagal memuat data member:\n$e';
        _loading = false;
      });
    }
  }

  Future<void> _submit() async {
    final jenis = _selectedJenis;
    final nama = _namaCtrl.text.trim();
    final pin = _pinCtrl.text.trim();
    if (jenis == null) {
      Fluttertoast.showToast(msg: 'Pilih jenis member dulu');
      return;
    }
    if (nama.isEmpty) {
      Fluttertoast.showToast(msg: 'Nama wajib diisi');
      return;
    }
    setState(() => _submitting = true);
    try {
      final resp = await _api.registerMember(
        jenis: jenis,
        nama: nama,
        pin: pin,
        noHp: _hpCtrl.text.trim(),
      );
      if (!mounted) return;
      if (resp['ok'] == true) {
        Fluttertoast.showToast(msg: resp['pesan'] ?? 'Member berhasil didaftarkan');
        Navigator.pop(context, true);
      } else {
        Fluttertoast.showToast(msg: resp['error'] ?? 'Gagal mendaftarkan member');
      }
    } catch (e) {
      if (!mounted) return;
      Fluttertoast.showToast(msg: 'Error: $e');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Daftar Member Baru')),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)))
          : _error.isNotEmpty
              ? ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Container(
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                        color: const Color(0xFF161B22),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: const Color(0xFFF85149)),
                      ),
                      child: Column(
                        children: [
                          const Icon(Icons.error_outline,
                              color: Color(0xFFF85149), size: 40),
                          const SizedBox(height: 12),
                          const Text(
                            'Tidak bisa memuat daftar jenis member.',
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              color: Color(0xFFF0F6FC),
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            _error,
                            style: const TextStyle(
                                fontSize: 12, color: Color(0xFF8B949E)),
                          ),
                          const SizedBox(height: 16),
                          ElevatedButton(
                            onPressed: _loadPlans,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: const Color(0xFF00E676),
                              foregroundColor: Colors.black,
                            ),
                            child: const Text('Coba Lagi'),
                          ),
                        ],
                      ),
                    ),
                  ],
                )
              : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(
                  'Pilih Jenis Member',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFFF0F6FC),
                  ),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: _jenis.map((j) {
                    final selected = j == _selectedJenis;
                    return ChoiceChip(
                      label: Text(j),
                      selected: selected,
                      onSelected: (_) => setState(() => _selectedJenis = j),
                      selectedColor: const Color(0xFF00E676),
                      labelStyle: TextStyle(
                        color: selected ? Colors.black : const Color(0xFFF0F6FC),
                        fontWeight: FontWeight.w600,
                      ),
                      backgroundColor: const Color(0xFF161B22),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(20),
                        side: const BorderSide(color: Color(0xFF21262D)),
                      ),
                    );
                  }).toList(),
                ),
                const SizedBox(height: 20),
                TextField(
                  controller: _namaCtrl,
                  style: const TextStyle(color: Color(0xFFF0F6FC)),
                  decoration: _inputDecoration('Nama Pemilik Member'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _hpCtrl,
                  keyboardType: TextInputType.phone,
                  style: const TextStyle(color: Color(0xFFF0F6FC)),
                  decoration: _inputDecoration('No. HP (opsional)'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _pinCtrl,
                  keyboardType: TextInputType.number,
                  obscureText: true,
                  maxLength: 6,
                  style: const TextStyle(color: Color(0xFFF0F6FC)),
                  decoration: const InputDecoration(
                    counterText: '',
                    labelText: 'PIN Member (4-6 digit)',
                    labelStyle: TextStyle(color: Color(0xFF8B949E)),
                    fillColor: Color(0xFF161B22),
                    filled: true,
                    border: OutlineInputBorder(
                      borderSide: BorderSide(color: Color(0xFF21262D)),
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  'PIN digunakan untuk memulai sesi TV dari HP.',
                  style: const TextStyle(fontSize: 12, color: Color(0xFF8B949E)),
                ),
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: _submitting ? null : _submit,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF00E676),
                    foregroundColor: Colors.black,
                    minimumSize: const Size.fromHeight(52),
                  ),
                  child: _submitting
                      ? const SizedBox(
                          width: 22,
                          height: 22,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Daftar Member'),
                ),
              ],
            ),
    );
  }

  InputDecoration _inputDecoration(String label) {
    return InputDecoration(
      labelText: label,
      labelStyle: const TextStyle(color: Color(0xFF8B949E)),
      fillColor: const Color(0xFF161B22),
      filled: true,
      border: const OutlineInputBorder(
        borderSide: BorderSide(color: Color(0xFF21262D)),
      ),
    );
  }
}