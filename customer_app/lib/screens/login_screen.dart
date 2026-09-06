import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../services/auth_service.dart';

class LoginScreen extends StatefulWidget {
  final String owner;
  const LoginScreen({super.key, required this.owner});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _auth = AuthService();
  bool _loading = false;
  String? _error;

  Future<void> _loginGoogle() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final err = await _auth.signInWithGoogle(widget.owner);
    if (!mounted) return;
    if (err == null) {
      context.go('/home');
    } else {
      setState(() {
        _error = err;
        _loading = false;
      });
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
              const SizedBox(height: 60),
              const Icon(
                Icons.sports_esports,
                size: 64,
                color: Color(0xFF00E676),
              ),
              const SizedBox(height: 16),
              const Text(
                'Masuk ke Akun Anda',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFF0F6FC),
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'Rental: ${widget.owner}',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 14,
                  color: Color(0xFF8B949E),
                ),
              ),
              const Spacer(),
              if (_error != null) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  margin: const EdgeInsets.only(bottom: 16),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF85149).withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _error!,
                    style: const TextStyle(color: Color(0xFFF85149), fontSize: 13),
                    textAlign: TextAlign.center,
                  ),
                ),
              ],
              ElevatedButton.icon(
                onPressed: _loading ? null : _loginGoogle,
                icon: _loading
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.black,
                        ),
                      )
                    : const Icon(Icons.g_mobiledata, size: 24),
                label: Text(_loading ? 'Masuk...' : 'Masuk dengan Google'),
              ),
              const SizedBox(height: 16),
              TextButton(
                onPressed: () => context.go('/kode-rental'),
                child: const Text(
                  'Ganti Rental',
                  style: TextStyle(color: Color(0xFF8B949E)),
                ),
              ),
              const SizedBox(height: 40),
            ],
          ),
        ),
      ),
    );
  }
}
