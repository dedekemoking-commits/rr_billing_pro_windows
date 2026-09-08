import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../services/api_service.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    _checkSession();
  }

  Future<void> _checkSession() async {
    await Future.delayed(const Duration(seconds: 2));
    if (!mounted) return;

    final api = ApiService();
    await api.loadSavedSession();

    if (api.isLoggedIn) {
      context.go('/home');
    } else {
      context.go('/kode-rental');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 100,
              height: 100,
              decoration: BoxDecoration(
                color: const Color(0xFF00E676),
                borderRadius: BorderRadius.circular(24),
              ),
              child: const Icon(
                Icons.sports_esports,
                size: 50,
                color: Colors.black,
              ),
            ),
            const SizedBox(height: 24),
            const Text(
              'RR Billing Pro',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.bold,
                color: Color(0xFFF0F6FC),
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              'Aplikasi Pelanggan',
              style: TextStyle(
                fontSize: 14,
                color: Color(0xFF8B949E),
              ),
            ),
            const SizedBox(height: 40),
            const CircularProgressIndicator(
              color: Color(0xFF00E676),
              strokeWidth: 2,
            ),
          ],
        ),
      ),
    );
  }
}
