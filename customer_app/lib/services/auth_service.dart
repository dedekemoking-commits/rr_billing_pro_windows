import 'package:flutter/foundation.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'api_service.dart';

class AuthService extends ChangeNotifier {
  final GoogleSignIn _googleSignIn = GoogleSignIn(
    scopes: ['email', 'profile'],
  );
  final ApiService _api = ApiService();

  GoogleSignInAccount? _googleUser;
  String? _customerToken;
  String? _owner;
  bool _isLoading = false;

  GoogleSignInAccount? get googleUser => _googleUser;
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

  Future<String?> signInWithGoogle(String ownerCode) async {
    _isLoading = true;
    notifyListeners();
    try {
      _googleUser = await _googleSignIn.signIn();
      if (_googleUser == null) {
        _isLoading = false;
        notifyListeners();
        return 'Login dibatalkan';
      }
      final idToken = await _getIdToken();
      if (idToken == null) {
        _isLoading = false;
        notifyListeners();
        return 'Gagal mendapatkan token Google';
      }

      // Coba login dulu
      try {
        final loginResp = await _api.login(idToken, ownerCode);
        if (loginResp['ok'] == true) {
          _customerToken = loginResp['token'];
          _owner = ownerCode;
          await _api.saveSession(_customerToken!, _owner!);
          _isLoading = false;
          notifyListeners();
          return null; // sukses
        }
      } catch (e) {
        // Login gagal, coba register
      }

      // Register
      final regResp = await _api.register(idToken, ownerCode);
      if (regResp['ok'] == true) {
        _customerToken = regResp['token'];
        _owner = ownerCode;
        await _api.saveSession(_customerToken!, _owner!);
        _isLoading = false;
        notifyListeners();
        return null; // sukses
      }
      _isLoading = false;
      notifyListeners();
      return regResp['error'] ?? 'Gagal mendaftar';
    } catch (e) {
      _isLoading = false;
      notifyListeners();
      return 'Error: $e';
    }
  }

  Future<String?> _getIdToken() async {
    // GoogleSignInAccount dinamis, kita gunakan authHeaders
    try {
      final auth = await _googleUser!.authentication;
      return auth.idToken;
    } catch (e) {
      return null;
    }
  }

  Future<void> signOut() async {
    await _googleSignIn.signOut();
    await _api.clearSession();
    _googleUser = null;
    _customerToken = null;
    _owner = null;
    notifyListeners();
  }

  void setOwner(String ownerCode) {
    _owner = ownerCode;
  }
}
