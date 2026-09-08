import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:fluttertoast/fluttertoast.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';
import '../../services/api_service.dart';
import '../../models/member.dart';

class IsiMemberScreen extends StatefulWidget {
  const IsiMemberScreen({super.key});

  @override
  State<IsiMemberScreen> createState() => _IsiMemberScreenState();
}

class _IsiMemberScreenState extends State<IsiMemberScreen> {
  final _api = ApiService();
  List<MemberCard> _members = [];
  MemberPlans? _plans;
  MemberCard? _selectedMember;
  MemberPaket? _selectedPaket;
  String _metode = 'QRIS';
  String? _buktiB64;
  String _buktiName = '';
  bool _loading = true;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    try {
      final results = await Future.wait([
        _api.listMembers(),
        _api.getMemberPlans(),
      ]);
      if (!mounted) return;
      setState(() {
        _members = (results[0]['members'] as List? ?? [])
            .map((e) => MemberCard.fromJson(e as Map<String, dynamic>))
            .toList();
        _plans = MemberPlans.fromJson(results[1]);
        if (_members.isNotEmpty && _selectedMember == null) {
          _selectedMember = _members.first;
        }
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
    }
  }

  Future<void> _pickBukti() async {
    final picker = ImagePicker();
    final file = await picker.pickImage(
      source: ImageSource.gallery,
      maxWidth: 1400,
      imageQuality: 70,
    );
    if (file == null) return;
    final bytes = await File(file.path).readAsBytes();
    if (!mounted) return;
    setState(() {
      _buktiB64 = 'data:image/png;base64,${base64Encode(bytes)}';
      _buktiName = file.name;
    });
  }

  Future<void> _submit() async {
    final member = _selectedMember;
    final paket = _selectedPaket;
    if (member == null || paket == null) {
      Fluttertoast.showToast(msg: 'Pilih member dan paket');
      return;
    }
    if (_metode == 'QRIS' && _buktiB64 == null) {
      Fluttertoast.showToast(msg: 'Upload bukti pembayaran QRIS dulu');
      return;
    }
    setState(() => _submitting = true);
    try {
      final resp = await _api.requestMemberTopup(
        memberId: member.id,
        paketNama: paket.nama,
        metode: _metode,
        bukti: _metode == 'QRIS' ? _buktiB64 ?? '' : '',
      );
      if (!mounted) return;
      if (resp['ok'] == true) {
        Fluttertoast.showToast(
            msg: resp['pesan'] ?? 'Permintaan terkirim, tunggu konfirmasi kasir');
        Navigator.pop(context, true);
      } else {
        Fluttertoast.showToast(msg: resp['error'] ?? 'Gagal mengirim permintaan');
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
    final plans =
        _selectedMember != null ? _plans?.plans[_selectedMember!.jenis] ?? [] : [];
    return Scaffold(
      appBar: AppBar(title: const Text('Isi Waktu Member')),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF00E676)))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_members.isEmpty)
                  const Padding(
                    padding: EdgeInsets.only(top: 40),
                    child: Text(
                      'Anda belum punya kartu member.\nDaftar dulu lewat menu "Daftar Member Baru".',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Color(0xFF8B949E)),
                    ),
                  )
                else ...[
                  _sectionTitle('Pilih Kartu Member'),
                  DropdownButtonFormField<MemberCard>(
                    initialValue: _selectedMember,
                    dropdownColor: const Color(0xFF161B22),
                    style: const TextStyle(color: Color(0xFFF0F6FC)),
                    decoration: _inputDecoration(),
                    items: _members
                        .map((m) => DropdownMenuItem(
                              value: m,
                              child: Text(
                                  '${m.jenis} · ${m.nama} (${m.saldoMenit} mnt)',
                                  overflow: TextOverflow.ellipsis),
                            ))
                        .toList(),
                    onChanged: (v) => setState(() {
                      _selectedMember = v;
                      _selectedPaket = null;
                    }),
                  ),
                  const SizedBox(height: 20),

                  _sectionTitle('Pilih Paket'),
                  if (plans.isEmpty)
                    const Text('Belum ada paket untuk jenis ini.',
                        style: TextStyle(color: Color(0xFF8B949E)))
                  else
                    ...plans.map((p) => GestureDetector(
                          onTap: () =>
                              setState(() => _selectedPaket = p),
                          child: Container(
                            margin: const EdgeInsets.only(bottom: 8),
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: const Color(0xFF161B22),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(
                                color: _selectedPaket == p
                                    ? const Color(0xFF00E676)
                                    : const Color(0xFF21262D),
                                width: _selectedPaket == p ? 1.6 : 1,
                              ),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.schedule,
                                    color: Color(0xFF00E676)),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Text(
                                    p.nama,
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w600,
                                      color: Color(0xFFF0F6FC),
                                    ),
                                  ),
                                ),
                                Text(
                                  NumberFormat.currency(
                                          locale: 'id_ID',
                                          symbol: 'Rp ',
                                          decimalDigits: 0)
                                      .format(p.harga),
                                  style: const TextStyle(
                                    fontWeight: FontWeight.bold,
                                    color: Color(0xFF00E676),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        )),
                  const SizedBox(height: 20),

                  _sectionTitle('Metode Pembayaran'),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(
                          value: 'QRIS',
                          icon: Icon(Icons.qr_code),
                          label: Text('QRIS')),
                      ButtonSegment(
                          value: 'Tunai',
                          icon: Icon(Icons.payments_outlined),
                          label: Text('Tunai')),
                    ],
                    selected: {_metode},
                    onSelectionChanged: (s) {
                      setState(() {
                        _metode = s.first;
                        _buktiB64 = null;
                        _buktiName = '';
                      });
                    },
                    style: SegmentedButton.styleFrom(
                      selectedForegroundColor: Colors.black,
                      selectedBackgroundColor: const Color(0xFF00E676),
                    ),
                  ),
                  const SizedBox(height: 12),

                  if (_metode == 'QRIS') ...[
                    const Text(
                      'Scan QRIS di counter kasir, lalu upload buktinya. '
                      'Saldo masuk setelah kasir menyetujui.',
                      style: TextStyle(fontSize: 12, color: Color(0xFF8B949E)),
                    ),
                    const SizedBox(height: 12),
                    ListTile(
                      tileColor: const Color(0xFF161B22),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                        side: const BorderSide(color: Color(0xFF21262D)),
                      ),
                      leading: _buktiB64 == null
                          ? const Icon(Icons.image_outlined,
                              color: Color(0xFF8B949E))
                          : const Icon(Icons.image, color: Color(0xFF00E676)),
                      title: Text(
                        _buktiB64 == null
                            ? 'Upload Bukti Transfer'
                            : _buktiName,
                        style: TextStyle(
                          color: _buktiB64 == null
                              ? const Color(0xFF8B949E)
                              : const Color(0xFFF0F6FC),
                        ),
                      ),
                      trailing: const Icon(Icons.photo_library_outlined,
                          color: Color(0xFF00E676)),
                      onTap: _pickBukti,
                    ),
                  ] else
                    const Text(
                      'Bayar tunai ke kasir, lalu minta konfirmasi.',
                      style: TextStyle(fontSize: 12, color: Color(0xFF8B949E)),
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
                        : const Text('Kirim Permintaan Isi Waktu'),
                  ),
                ],
              ],
            ),
    );
  }

  Widget _sectionTitle(String t) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Text(
        t,
        style: const TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w600,
          color: Color(0xFFF0F6FC),
        ),
      ),
    );
  }

  InputDecoration _inputDecoration() {
    return const InputDecoration(
      labelText: 'Kartu Member',
      labelStyle: TextStyle(color: Color(0xFF8B949E)),
      fillColor: Color(0xFF161B22),
      filled: true,
      border: OutlineInputBorder(
        borderSide: BorderSide(color: Color(0xFF21262D)),
      ),
    );
  }
}