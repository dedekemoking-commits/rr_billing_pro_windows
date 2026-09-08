import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../config/api.dart';

class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  late final Dio _dio;
  String? _customerToken;
  String? _owner;

  ApiService._internal() {
    _dio = Dio(BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
      headers: {'Content-Type': 'application/json'},
    ));
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) {
        if (_customerToken != null) {
          options.headers['X-Customer-Token'] = _customerToken;
        }
        handler.next(options);
      },
      onError: (error, handler) {
        handler.next(error);
      },
    ));
  }

  String? get owner => _owner;
  String? get customerToken => _customerToken;

  Future<void> loadSavedSession() async {
    final prefs = await SharedPreferences.getInstance();
    _customerToken = prefs.getString('customer_token');
    _owner = prefs.getString('owner');
  }

  Future<void> saveSession(String token, String owner) async {
    _customerToken = token;
    _owner = owner;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('customer_token', token);
    await prefs.setString('owner', owner);
  }

  Future<void> clearSession() async {
    _customerToken = null;
    _owner = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('customer_token');
    await prefs.remove('owner');
  }

  bool get isLoggedIn => _customerToken != null && _owner != null;

  // ── Cek Rental ──────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> cekRental(String owner) async {
    final resp = await _dio.get('/api/customer/cek-rental',
        queryParameters: {'owner': owner});
    return resp.data;
  }

  // ── Register ────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> register(String idToken, String owner) async {
    final resp = await _dio.post('/api/customer/register',
        data: {'idToken': idToken, 'owner': owner});
    return resp.data;
  }

  // ── Login ───────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> login(String idToken, String owner) async {
    final resp = await _dio.post('/api/customer/login',
        data: {'idToken': idToken, 'owner': owner});
    return resp.data;
  }

  // ── Login manual (tanpa Google/Firebase) ────────────────────────────────
  Future<Map<String, dynamic>> loginManual({
    required String owner,
    required String nama,
    required String email,
    String hp = '',
  }) async {
    final resp = await _dio.post('/api/customer/login-manual',
        data: {
          'owner': owner,
          'nama': nama,
          'email': email,
          'hp': hp,
        });
    return resp.data;
  }

  // ── Profile ─────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> getProfile() async {
    final resp = await _dio.get('/api/customer/profile');
    return resp.data;
  }

  Future<Map<String, dynamic>> updateProfile(Map<String, dynamic> data) async {
    final resp = await _dio.put('/api/customer/profile', data: data);
    return resp.data;
  }

  // ── Saldo ───────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> getSaldo() async {
    final resp = await _dio.get('/api/customer/saldo');
    return resp.data;
  }

  // ── Booking ─────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> createBooking(Map<String, dynamic> data) async {
    final resp = await _dio.post('/api/customer/booking', data: data);
    return resp.data;
  }

  Future<Map<String, dynamic>> listBooking() async {
    final resp = await _dio.get('/api/customer/booking');
    return resp.data;
  }

  Future<Map<String, dynamic>> checkSlot(
      String perangkat, String tanggal, String jam) async {
    final resp = await _dio.get('/api/customer/booking/check',
        queryParameters: {
          'perangkat': perangkat,
          'tanggal': tanggal,
          'jam': jam,
        });
    return resp.data;
  }

  // ── Riwayat ─────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> getRiwayat() async {
    final resp = await _dio.get('/api/customer/riwayat');
    return resp.data;
  }

  // ── Riwayat Transaksi (booking + order + top-up) ────────────────────────
  Future<Map<String, dynamic>> getTransaksi() async {
    final resp = await _dio.get('/api/customer/transaksi');
    return resp.data;
  }

  // ── Promo ───────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> getPromo() async {
    final resp = await _dio.get('/api/customer/promo');
    return resp.data;
  }

  // ── Voucher ─────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> redeemVoucher(String kode) async {
    final resp = await _dio.post('/api/customer/voucher',
        data: {'kode': kode});
    return resp.data;
  }

  // ── Menu F&B ────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> getMenu() async {
    final resp = await _dio.get('/api/customer/menu');
    return resp.data;
  }

  // ── Order F&B ──────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> createOrder(
      List<Map<String, dynamic>> items, String catatan) async {
    final resp = await _dio.post('/api/customer/order',
        data: {'items': items, 'catatan': catatan});
    return resp.data;
  }

  // ── FCM Token ──────────────────────────────────────────────────────────
  Future<void> saveFcmToken(String fcmToken) async {
    await _dio.post('/api/customer/fcm-token',
        data: {'fcm_token': fcmToken});
  }

  // ── Member ─────────────────────────────────────────────────────────────
  Future<Map<String, dynamic>> getMemberPlans() async {
    final resp = await _dio.get('/api/customer/member/plans');
    return resp.data;
  }

  Future<Map<String, dynamic>> registerMember({
    required String jenis,
    required String nama,
    required String pin,
    String noHp = '',
  }) async {
    final resp = await _dio.post('/api/customer/member/register',
        data: {'jenis': jenis, 'nama': nama, 'pin': pin, 'no_hp': noHp});
    return resp.data;
  }

  Future<Map<String, dynamic>> listMembers() async {
    final resp = await _dio.get('/api/customer/member/list');
    return resp.data;
  }

  Future<Map<String, dynamic>> requestMemberTopup({
    required String memberId,
    required String paketNama,
    required String metode,
    String bukti = '',
  }) async {
    final resp = await _dio.post('/api/customer/member/topup',
        data: {
          'member_id': memberId,
          'paket_nama': paketNama,
          'metode': metode,
          'bukti': bukti,
        });
    return resp.data;
  }

  Future<Map<String, dynamic>> getMemberTopupStatus() async {
    final resp = await _dio.get('/api/customer/member/topup/status');
    return resp.data;
  }

  Future<Map<String, dynamic>> getMemberTvs() async {
    final resp = await _dio.get('/api/customer/member/tvs');
    return resp.data;
  }

  Future<Map<String, dynamic>> startMemberSession({
    required String memberId,
    required String tvLabel,
    required String pin,
  }) async {
    final resp = await _dio.post('/api/customer/member/start',
        data: {'member_id': memberId, 'tv_label': tvLabel, 'pin': pin});
    return resp.data;
  }
}
