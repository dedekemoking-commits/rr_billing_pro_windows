import 'package:flutter/material.dart';
import 'package:fluttertoast/fluttertoast.dart';
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
  final _formKey = GlobalKey<FormState>();
  final _namaCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _hpCtrl = TextEditingController();
  bool _loading = false;

  @override
  void dispose() {
    _namaCtrl.dispose();
    _emailCtrl.dispose();
    _hpCtrl.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    if (!_formKey.currentState!.validate()) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _loading = true;
    });
    final err = await _auth.signInManual(
      ownerCode: widget.owner,
      nama: _namaCtrl.text.trim(),
      email: _emailCtrl.text.trim(),
      hp: _hpCtrl.text.trim(),
    );
    if (!mounted) return;
    if (err == null) {
      context.go('/home');
    } else {
      setState(() {
        _loading = false;
      });
      Fluttertoast.showToast(
          msg: err, toastLength: Toast.LENGTH_LONG, gravity: ToastGravity.CENTER);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
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
                  const SizedBox(height: 32),
                  TextFormField(
                    controller: _namaCtrl,
                    style: const TextStyle(color: Color(0xFFF0F6FC)),
                    decoration: _dec('Nama Lengkap', Icons.person_outline),
                    textInputAction: TextInputAction.next,
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? 'Nama wajib diisi' : null,
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _emailCtrl,
                    style: const TextStyle(color: Color(0xFFF0F6FC)),
                    decoration: _dec('Email', Icons.mail_outline),
                    keyboardType: TextInputType.emailAddress,
                    textInputAction: TextInputAction.next,
                    validator: (v) {
                      if (v == null || v.trim().isEmpty) return 'Email wajib diisi';
                      if (!v.contains('@')) return 'Email tidak valid';
                      return null;
                    },
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _hpCtrl,
                    style: const TextStyle(color: Color(0xFFF0F6FC)),
                    decoration: _dec('No. HP (opsional)', Icons.phone_outlined),
                    keyboardType: TextInputType.phone,
                    textInputAction: TextInputAction.done,
                    onFieldSubmitted: (_) => _loading ? null : _login(),
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: _loading ? null : _login,
                    child: _loading
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.black,
                            ),
                          )
                        : const Text('Masuk'),
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
        ),
      ),
    );
  }

  InputDecoration _dec(String label, IconData icon) {
    return InputDecoration(
      labelText: label,
      labelStyle: const TextStyle(color: Color(0xFF8B949E)),
      icon: Icon(icon, color: Color(0xFF58A6FF)),
      enabledBorder: const UnderlineInputBorder(
        borderSide: BorderSide(color: Color(0xFF30363D)),
      ),
      focusedBorder: const UnderlineInputBorder(
        borderSide: BorderSide(color: Color(0xFF58A6FF)),
      ),
    );
  }
}