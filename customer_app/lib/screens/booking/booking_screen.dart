import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import '../../services/api_service.dart';

class BookingScreen extends StatefulWidget {
  const BookingScreen({super.key});

  @override
  State<BookingScreen> createState() => _BookingScreenState();
}

class _BookingScreenState extends State<BookingScreen> {
  final _api = ApiService();
  final _dateController = TextEditingController();
  final _timeController = TextEditingController();
  final _noteController = TextEditingController();

  List<String> _devices = [];
  List<Map<String, dynamic>> _packages = [];
  String? _selectedDevice;
  String? _selectedPackage;
  String? _selectedGroup;
  bool _loading = true;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _loadMenu();
  }

  Future<void> _loadMenu() async {
    try {
      final resp = await _api.getMenu();
      // Get devices from call_meta
      final menuResp = await _api.getMenu();
      // For now, load available data
      setState(() => _loading = false);
    } catch (e) {
      setState(() => _loading = false);
    }
  }

  Future<void> _pickDate() async {
    final date = await showDatePicker(
      context: context,
      initialDate: DateTime.now(),
      firstDate: DateTime.now(),
      lastDate: DateTime.now().add(const Duration(days: 30)),
    );
    if (date != null) {
      setState(() {
        _dateController.text = DateFormat('yyyy-MM-dd').format(date);
      });
    }
  }

  Future<void> _pickTime() async {
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.now(),
    );
    if (time != null) {
      setState(() {
        _timeController.text = '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
      });
    }
  }

  Future<void> _submit() async {
    if (_selectedDevice == null || _selectedPackage == null ||
        _dateController.text.isEmpty || _timeController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Lengkapi semua data booking')),
      );
      return;
    }
    setState(() => _submitting = true);
    try {
      final resp = await _api.createBooking({
        'perangkat': _selectedDevice,
        'grup': _selectedGroup ?? '',
        'paket': _selectedPackage,
        'tanggal': _dateController.text,
        'jam': _timeController.text,
        'metode': 'biasa',
        'catatan': _noteController.text,
      });
      if (!mounted) return;
      if (resp['ok'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Booking berhasil! Menunggu konfirmasi kasir.'),
            backgroundColor: Color(0xFF3FB950),
          ),
        );
        context.pop();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(resp['error'] ?? 'Gagal membuat booking')),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error: $e')),
      );
    }
    setState(() => _submitting = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Booking Baru')),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const Text('Pilih Perangkat',
                    style: TextStyle(color: Color(0xFF8B949E), fontSize: 13)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: ['TV-1', 'TV-2', 'TV-3', 'PS-1', 'PS-2'].map((d) {
                    final selected = _selectedDevice == d;
                    return ChoiceChip(
                      label: Text(d),
                      selected: selected,
                      selectedColor: const Color(0xFF00E676),
                      backgroundColor: const Color(0xFF21262D),
                      labelStyle: TextStyle(
                        color: selected ? Colors.black : const Color(0xFFF0F6FC),
                      ),
                      onSelected: (_) => setState(() => _selectedDevice = d),
                    );
                  }).toList(),
                ),
                const SizedBox(height: 20),

                const Text('Tanggal',
                    style: TextStyle(color: Color(0xFF8B949E), fontSize: 13)),
                const SizedBox(height: 8),
                TextField(
                  controller: _dateController,
                  readOnly: true,
                  onTap: _pickDate,
                  decoration: const InputDecoration(
                    hintText: 'Pilih tanggal',
                    prefixIcon: Icon(Icons.calendar_today, color: Color(0xFF8B949E)),
                  ),
                ),
                const SizedBox(height: 16),

                const Text('Jam',
                    style: TextStyle(color: Color(0xFF8B949E), fontSize: 13)),
                const SizedBox(height: 8),
                TextField(
                  controller: _timeController,
                  readOnly: true,
                  onTap: _pickTime,
                  decoration: const InputDecoration(
                    hintText: 'Pilih jam',
                    prefixIcon: Icon(Icons.access_time, color: Color(0xFF8B949E)),
                  ),
                ),
                const SizedBox(height: 20),

                const Text('Paket',
                    style: TextStyle(color: Color(0xFF8B949E), fontSize: 13)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    _packageChip('30 Menit', '30 Menit'),
                    _packageChip('1 Jam', '1 Jam'),
                    _packageChip('2 Jam', '2 Jam'),
                    _packageChip('3 Jam', '3 Jam'),
                    _packageChip('5 Jam', '5 Jam'),
                    _packageChip('Overnight', 'Overnight'),
                  ],
                ),
                const SizedBox(height: 16),

                TextField(
                  controller: _noteController,
                  maxLines: 2,
                  decoration: const InputDecoration(
                    hintText: 'Catatan (opsional)',
                  ),
                ),
                const SizedBox(height: 24),

                ElevatedButton(
                  onPressed: _submitting ? null : _submit,
                  child: _submitting
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black),
                        )
                      : const Text('Kirim Booking'),
                ),
              ],
            ),
    );
  }

  Widget _packageChip(String label, String value) {
    final selected = _selectedPackage == value;
    return ChoiceChip(
      label: Text(label),
      selected: selected,
      selectedColor: const Color(0xFF00E676),
      backgroundColor: const Color(0xFF21262D),
      labelStyle: TextStyle(
        color: selected ? Colors.black : const Color(0xFFF0F6FC),
      ),
      onSelected: (_) => setState(() {
        _selectedPackage = value;
        _selectedGroup = 'Reguler';
      }),
    );
  }
}
