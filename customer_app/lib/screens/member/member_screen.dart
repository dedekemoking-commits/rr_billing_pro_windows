import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../services/api_service.dart';
import '../../models/member.dart';

class MemberScreen extends StatefulWidget {
  const MemberScreen({super.key});

  @override
  State<MemberScreen> createState() => _MemberScreenState();
}

class _MemberScreenState extends State<MemberScreen> {
  final _api = ApiService();
  List<MemberCard> _members = [];
  List<MemberTopup> _topups = [];
  List<Map<String, dynamic>> _activeSessions = [];
  bool _loading = true;
  String _error = '';

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _loading = true;
      _error = '';
    });
    try {
      final results = await Future.wait([
        _api.listMembers(),
        _api.getMemberTopupStatus(),
        _api.getActiveMemberSessions(),
      ]);
      if (!mounted) return;
      setState(() {
        _members = (results[0]['members'] as List? ?? [])
            .map((e) => MemberCard.fromJson(e as Map<String, dynamic>))
            .toList();
        _topups = (results[1]['topups'] as List? ?? [])
            .map((e) => MemberTopup.fromJson(e as Map<String, dynamic>))
            .toList();
        _activeSessions = (results[2]['sessions'] as List? ?? [])
            .map((e) => Map<String, dynamic>.from(e as Map))
            .toList();
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

  Future<void> _finishSession(Map<String, dynamic> session) async {
    final pinCtrl = TextEditingController();
    final pin = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF161B22),
        title: const Text('Selesaikan Sesi',
            style: TextStyle(color: Color(0xFFF0F6FC))),
        content: TextField(
          controller: pinCtrl,
          autofocus: true,
          obscureText: true,
          keyboardType: TextInputType.number,
          maxLength: 6,
          decoration: const InputDecoration(
              labelText: 'PIN Member',
              labelStyle: TextStyle(color: Color(0xFF8B949E))),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Batal')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, pinCtrl.text.trim()),
            child: const Text('Selesai'),
          ),
        ],
      ),
    );
    pinCtrl.dispose();
    if (pin == null || pin.isEmpty || !mounted) return;
    try {
      final result = await _api.finishMemberSession(
          memberId: session['member_id'] as String, pin: pin);
      if (!mounted) return;
      if (result['ok'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(
                'Sesi selesai. Terpakai ${result['dipakai_menit']} menit.')));
        await _loadData();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Gagal menyelesaikan sesi: $e')));
      }
    }
  }

  Color _jenisColor(String jenis) {
    switch (jenis) {
      case 'VIP':
        return const Color(0xFFF78166);
      case 'PS3':
        return const Color(0xFF58A6FF);
      case 'PS4':
        return const Color(0xFF00E676);
      case 'PS5':
        return const Color(0xFF3FB950);
      default:
        return const Color(0xFF8B949E);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Member Saya')),
      body: _loading
          ? const Center(
              child: CircularProgressIndicator(color: Color(0xFF00E676)))
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
                            'Tidak bisa memuat data member. '
                            'Pastikan sudah login ulang setelah server restart.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              color: Color(0xFFF0F6FC),
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(_error,
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                  fontSize: 12, color: Color(0xFF8B949E))),
                          if (_activeSessions.isNotEmpty) ...[
                            const SizedBox(height: 4),
                            const Text('Sesi Aktif',
                                style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                    color: Color(0xFFF0F6FC))),
                            const SizedBox(height: 8),
                            ..._activeSessions.map((s) => Card(
                                  color: const Color(0xFF16351F),
                                  child: ListTile(
                                    leading: const Icon(Icons.tv,
                                        color: Color(0xFF00E676)),
                                    title: Text(
                                        '${s['nama_member']} · TV ${s['label']}',
                                        style: const TextStyle(
                                            color: Color(0xFFF0F6FC))),
                                    subtitle: Text(
                                        'Sisa ${s['sisa_menit']} menit · terpakai ${s['dipakai_menit']} menit',
                                        style: const TextStyle(
                                            color: Color(0xFFB7E4C7))),
                                    trailing: SizedBox(
                                      width: 88,
                                      child: ElevatedButton(
                                        onPressed: () => _finishSession(s),
                                        style: ElevatedButton.styleFrom(
                                          minimumSize: const Size(0, 40),
                                          padding: const EdgeInsets.symmetric(
                                              horizontal: 8),
                                        ),
                                        child: const Text('Selesai'),
                                      ),
                                    ),
                                  ),
                                )),
                            const SizedBox(height: 12),
                          ],
                          const SizedBox(height: 16),
                          ElevatedButton(
                            onPressed: _loadData,
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
              : RefreshIndicator(
                  onRefresh: _loadData,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      if (_members.isEmpty)
                        Container(
                          padding: const EdgeInsets.all(24),
                          decoration: BoxDecoration(
                            color: const Color(0xFF161B22),
                            borderRadius: BorderRadius.circular(16),
                            border: Border.all(color: const Color(0xFF21262D)),
                          ),
                          child: const Column(
                            children: [
                              Icon(Icons.credit_card_off,
                                  color: Color(0xFF8B949E), size: 40),
                              SizedBox(height: 12),
                              Text(
                                'Belum ada kartu member.\nDaftar sekarang untuk isi waktu dari HP!',
                                textAlign: TextAlign.center,
                                style: TextStyle(color: Color(0xFF8B949E)),
                              ),
                            ],
                          ),
                        )
                      else
                        ..._members.map((m) => Container(
                              margin: const EdgeInsets.only(bottom: 12),
                              padding: const EdgeInsets.all(16),
                              decoration: BoxDecoration(
                                color: const Color(0xFF161B22),
                                borderRadius: BorderRadius.circular(16),
                                border:
                                    Border.all(color: const Color(0xFF21262D)),
                              ),
                              child: Row(
                                children: [
                                  Container(
                                    width: 48,
                                    height: 48,
                                    alignment: Alignment.center,
                                    decoration: BoxDecoration(
                                      color: _jenisColor(m.jenis)
                                          .withOpacity(0.15),
                                      borderRadius: BorderRadius.circular(12),
                                    ),
                                    child: Text(
                                      m.jenis,
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: FontWeight.bold,
                                        color: _jenisColor(m.jenis),
                                      ),
                                    ),
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          m.nama,
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w600,
                                            color: Color(0xFFF0F6FC),
                                            fontSize: 15,
                                          ),
                                        ),
                                        Text(
                                          '${m.jenis} Member',
                                          style: const TextStyle(
                                            fontSize: 12,
                                            color: Color(0xFF8B949E),
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  Column(
                                    crossAxisAlignment: CrossAxisAlignment.end,
                                    children: [
                                      Text(
                                        '${m.saldoMenit} Menit',
                                        style: const TextStyle(
                                          fontWeight: FontWeight.bold,
                                          color: Color(0xFF00E676),
                                          fontSize: 16,
                                        ),
                                      ),
                                      Text(
                                        m.status == 'aktif'
                                            ? 'Aktif'
                                            : m.status,
                                        style: TextStyle(
                                          fontSize: 11,
                                          color: m.status == 'aktif'
                                              ? const Color(0xFF3FB950)
                                              : const Color(0xFFF85149),
                                        ),
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            )),
                      const SizedBox(height: 16),
                      const Text(
                        'Aksi',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: Color(0xFFF0F6FC),
                        ),
                      ),
                      const SizedBox(height: 12),
                      _actionTile(
                        icon: Icons.add_card,
                        label: 'Daftar Member Baru',
                        desc: 'Buat kartu member (PS3/PS4/PS5/VIP)',
                        onTap: () async {
                          await context.push('/member/daftar');
                          _loadData();
                        },
                      ),
                      _actionTile(
                        icon: Icons.add_circle_outline,
                        label: 'Isi Waktu / Top Up',
                        desc: 'QRIS (upload bukti) atau bayar tunai ke kasir',
                        onTap: () async {
                          await context.push('/member/isi');
                          _loadData();
                        },
                      ),
                      _actionTile(
                        icon: Icons.play_circle_outline,
                        label: 'Mulai Sesi',
                        desc: 'Nyalakan TV member dari HP',
                        onTap: () => context.push('/member/mulai'),
                      ),
                      const SizedBox(height: 16),
                      if (_topups.isNotEmpty) ...[
                        const Text(
                          'Riwayat Top Up Member',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                            color: Color(0xFFF0F6FC),
                          ),
                        ),
                        const SizedBox(height: 8),
                        ..._topups.take(5).map((t) => Container(
                              margin: const EdgeInsets.only(bottom: 8),
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: const Color(0xFF161B22),
                                borderRadius: BorderRadius.circular(12),
                                border:
                                    Border.all(color: const Color(0xFF21262D)),
                              ),
                              child: Row(
                                children: [
                                  Icon(
                                    t.status == 'disetujui'
                                        ? Icons.check_circle
                                        : t.status == 'ditolak'
                                            ? Icons.cancel
                                            : Icons.hourglass_empty,
                                    color: t.status == 'disetujui'
                                        ? const Color(0xFF3FB950)
                                        : t.status == 'ditolak'
                                            ? const Color(0xFFF85149)
                                            : const Color(0xFFF78166),
                                    size: 22,
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          '${t.jenis} · ${t.paket}',
                                          style: const TextStyle(
                                            fontSize: 13,
                                            fontWeight: FontWeight.w600,
                                            color: Color(0xFFF0F6FC),
                                          ),
                                        ),
                                        Text(
                                          '${t.harga} · ${t.metode}',
                                          style: const TextStyle(
                                            fontSize: 11,
                                            color: Color(0xFF8B949E),
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  Text(
                                    t.status == 'menunggu'
                                        ? 'Menunggu Kasir'
                                        : t.status == 'disetujui'
                                            ? '+${t.menit} mnt'
                                            : (t.alasan.isEmpty
                                                ? 'Ditolak'
                                                : t.alasan),
                                    style: TextStyle(
                                      fontSize: 11,
                                      color: t.status == 'menunggu'
                                          ? const Color(0xFFF78166)
                                          : t.status == 'disetujui'
                                              ? const Color(0xFF3FB950)
                                              : const Color(0xFFF85149),
                                    ),
                                  ),
                                ],
                              ),
                            )),
                      ],
                    ],
                  ),
                ),
    );
  }

  Widget _actionTile({
    required IconData icon,
    required String label,
    required String desc,
    required VoidCallback onTap,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: Color(0xFF21262D)),
        ),
        tileColor: const Color(0xFF161B22),
        leading: Icon(icon, color: const Color(0xFF00E676)),
        title: Text(
          label,
          style: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: Color(0xFFF0F6FC),
          ),
        ),
        subtitle: Text(
          desc,
          style: const TextStyle(fontSize: 12, color: Color(0xFF8B949E)),
        ),
        trailing: const Icon(Icons.chevron_right, color: Color(0xFF8B949E)),
        onTap: onTap,
      ),
    );
  }
}
