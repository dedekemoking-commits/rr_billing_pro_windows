import 'package:flutter/material.dart';
import 'package:fluttertoast/fluttertoast.dart';
import '../../services/api_service.dart';
import '../../models/member.dart';

class MulaiSesiScreen extends StatefulWidget {
  const MulaiSesiScreen({super.key});

  @override
  State<MulaiSesiScreen> createState() => _MulaiSesiScreenState();
}

class _MulaiSesiScreenState extends State<MulaiSesiScreen> {
  final _api = ApiService();
  final _pinCtrl = TextEditingController();
  List<MemberCard> _members = [];
  MemberTvMap? _tvMap;
  MemberCard? _selectedMember;
  MemberTv? _selectedTv;
  bool _loading = true;
  bool _starting = false;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  @override
  void dispose() {
    _pinCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadData() async {
    try {
      final results = await Future.wait([
        _api.listMembers(),
        _api.getMemberTvs(),
      ]);
      if (!mounted) return;
      setState(() {
        _members = (results[0]['members'] as List? ?? [])
            .map((e) => MemberCard.fromJson(e as Map<String, dynamic>))
            .toList()
            .where((m) => m.saldoMenit > 0 && m.status == 'aktif')
            .toList();
        _tvMap = MemberTvMap.fromJson(results[1]);
        if (_members.isNotEmpty && _selectedMember == null) {
          _selectedMember = _members.first;
          _autoPickTv();
        }
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
    }
  }

  void _onMemberChanged(MemberCard? m) {
    setState(() {
      _selectedMember = m;
      _selectedTv = null;
      _autoPickTv();
    });
  }

  void _autoPickTv() {
    final m = _selectedMember;
    if (m == null || _tvMap == null) return;
    final tvs = _tvMap!.tvs[m.jenis] ?? [];
    _selectedTv = tvs.isNotEmpty ? tvs.first : null;
  }

  Future<void> _start() async {
    final m = _selectedMember;
    final tv = _selectedTv;
    final pin = _pinCtrl.text.trim();
    if (m == null || tv == null) {
      Fluttertoast.showToast(msg: 'Tidak ada TV kosong yang cocok');
      return;
    }
    if (pin.isEmpty) {
      Fluttertoast.showToast(msg: 'Masukkan PIN member');
      return;
    }
    setState(() => _starting = true);
    try {
      final resp = await _api.startMemberSession(
        memberId: m.id,
        tvLabel: tv.label,
        pin: pin,
      );
      if (!mounted) return;
      if (resp['ok'] == true) {
        final r = MemberStartResult.fromJson(resp);
        _showStartDialog(r);
      } else {
        Fluttertoast.showToast(msg: resp['error'] ?? 'Gagal memulai sesi');
      }
    } catch (e) {
      if (!mounted) return;
      Fluttertoast.showToast(msg: 'Error: $e');
    } finally {
      if (mounted) setState(() => _starting = false);
    }
  }

  void _showStartDialog(MemberStartResult r) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF161B22),
        title: const Icon(Icons.check_circle,
            color: Color(0xFF3FB950), size: 48),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'Sesi dimulai!',
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.bold,
                color: Color(0xFFF0F6FC),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              'Member ${r.namaMember}\nTV ${r.label}\nSisa ${r.sisaMenit} menit',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Color(0xFFF0F6FC), height: 1.5),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('OK', style: TextStyle(color: Color(0xFF00E676))),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    List<MemberTv> tvs =
        _selectedMember != null ? _tvMap?.tvs[_selectedMember!.jenis] ?? [] : [];
    if (_selectedTv != null && !tvs.contains(_selectedTv)) {
      tvs = [...tvs, _selectedTv!];
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Mulai Sesi Member')),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_members.isEmpty)
                  const Padding(
                    padding: EdgeInsets.only(top: 40),
                    child: Text(
                      'Tidak ada kartu member aktif dengan saldo.\nIsi waktu dulu lalu tunggu konfirmasi kasir.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Color(0xFF8B949E)),
                    ),
                  )
                else ...[
                  const Text(
                    'Pilih Kartu Member',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFFF0F6FC),
                    ),
                  ),
                  const SizedBox(height: 10),
                  DropdownButtonFormField<MemberCard>(
                    initialValue: _selectedMember,
                    dropdownColor: const Color(0xFF161B22),
                    style: const TextStyle(color: Color(0xFFF0F6FC)),
                    decoration: const InputDecoration(
                      labelText: 'Kartu Member',
                      labelStyle: TextStyle(color: Color(0xFF8B949E)),
                      fillColor: Color(0xFF161B22),
                      filled: true,
                      border: OutlineInputBorder(
                        borderSide: BorderSide(color: Color(0xFF21262D)),
                      ),
                    ),
                    items: _members
                        .map((m) => DropdownMenuItem(
                              value: m,
                              child: Text(
                                  '${m.jenis} · ${m.nama} (${m.saldoMenit} mnt)',
                                  overflow: TextOverflow.ellipsis),
                            ))
                        .toList(),
                    onChanged: _onMemberChanged,
                  ),
                  const SizedBox(height: 20),

                  const Text(
                    'Pilih TV',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFFF0F6FC),
                    ),
                  ),
                  const SizedBox(height: 10),
                  if (tvs.isEmpty)
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: const Color(0xFF161B22),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Text(
                        'Belum ada TV kosong yang cocok untuk jenis member ini. '
                        'Hubungi kasir.',
                        style: TextStyle(fontSize: 12, color: Color(0xFF8B949E)),
                      ),
                    )
                  else
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: tvs.map((tv) {
                        final selected = tv.label == _selectedTv?.label;
                        return ChoiceChip(
                          label: Text(tv.label,
                              style: TextStyle(
                                color: selected
                                    ? Colors.black
                                    : const Color(0xFFF0F6FC),
                                fontWeight: FontWeight.w600,
                              )),
                          selected: selected,
                          onSelected: (_) =>
                              setState(() => _selectedTv = tv),
                          selectedColor: const Color(0xFF00E676),
                          backgroundColor: const Color(0xFF161B22),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(20),
                            side: const BorderSide(color: Color(0xFF21262D)),
                          ),
                        );
                      }).toList(),
                    ),
                  const SizedBox(height: 20),

                  const Text(
                    'PIN Member',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFFF0F6FC),
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _pinCtrl,
                    keyboardType: TextInputType.number,
                    obscureText: true,
                    maxLength: 6,
                    style: const TextStyle(color: Color(0xFFF0F6FC)),
                    decoration: const InputDecoration(
                      counterText: '',
                      labelText: 'Masukkan PIN',
                      labelStyle: TextStyle(color: Color(0xFF8B949E)),
                      fillColor: Color(0xFF161B22),
                      filled: true,
                      border: OutlineInputBorder(
                        borderSide: BorderSide(color: Color(0xFF21262D)),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),

                  ElevatedButton.icon(
                    onPressed: _starting ? null : _start,
                    icon: const Icon(Icons.power_settings_new, color: Colors.black),
                    label: _starting
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Nyalakan TV Member',
                            style: TextStyle(color: Colors.black)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF00E676),
                      minimumSize: const Size.fromHeight(52),
                    ),
                  ),
                ],
              ],
            ),
    );
  }
}