import 'package:flutter/foundation.dart';
import 'api_service.dart';

class AuthService extends ChangeNotifier {
  final ApiService _api = ApiService();

  String? _customerToken;
  String? _owner;
  bool _isLoading = false;

  String? get customerToken => _customerToken;
  String? get owner => _owner;
  bool get isLoading => _isLoading;
  bool get isLoggedIn => _customerToken != null && _owner != null;

  Future<void> init() async {
    await _api.loadSavedSession();
    _customerToken = _api.customerToken;
    _owner = _api.owner;
    notifyListeners();
  }

  Future<String?> signInManual({
    required String ownerCode,
    required String nama,
    required String email,
    String hp = '',
  }) async {
    _isLoading = true;
    notifyListeners();
    try {
      final resp = await _api.loginManual(
        owner: ownerCode,
        nama: nama,
        email: email,
        hp: hp,
      );
      if (resp['ok'] == true) {
        _customerToken = resp['token'];
        _owner = ownerCode;
        await _api.saveSession(_customerToken!, _owner!);
        _isLoading = false;
        notifyListeners();
        return null; // sukses
      }
      _isLoading = false;
      notifyListeners();
      return resp['error'] ?? 'Gagal masuk';
    } catch (e) {
      _isLoading = false;
      notifyListeners();
      return 'Error: $e';
    }
  }

  Future<void> signOut() async {
    await _api.clearSession();
    _customerToken = null;
    _owner = null;
    notifyListeners();
  }

  void setOwner(String ownerCode) {
    _owner = ownerCode;
  }
}