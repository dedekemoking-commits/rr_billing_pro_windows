import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'config/theme.dart';
import 'screens/splash_screen.dart';
import 'screens/kode_rental_screen.dart';
import 'screens/login_screen.dart';
import 'screens/home_screen.dart';
import 'screens/booking/booking_screen.dart';
import 'screens/riwayat_screen.dart';
import 'screens/saldo/topup_screen.dart';
import 'screens/promo/voucher_screen.dart';
import 'screens/menu/menu_screen.dart';
import 'screens/profil/profil_screen.dart';

final goRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(
        path: '/',
        builder: (context, state) => const SplashScreen(),
      ),
      GoRoute(
        path: '/kode-rental',
        builder: (context, state) => const KodeRentalScreen(),
      ),
      GoRoute(
        path: '/login',
        builder: (context, state) {
          final owner = state.extra as String? ?? '';
          return LoginScreen(owner: owner);
        },
      ),
      GoRoute(
        path: '/home',
        builder: (context, state) => const HomeScreen(),
      ),
      GoRoute(
        path: '/booking',
        builder: (context, state) => const BookingScreen(),
      ),
      GoRoute(
        path: '/riwayat',
        builder: (context, state) => const RiwayatScreen(),
      ),
      GoRoute(
        path: '/topup',
        builder: (context, state) => const TopUpScreen(),
      ),
      GoRoute(
        path: '/voucher',
        builder: (context, state) => const VoucherScreen(),
      ),
      GoRoute(
        path: '/menu',
        builder: (context, state) => const MenuScreen(),
      ),
      GoRoute(
        path: '/profil',
        builder: (context, state) => const ProfilScreen(),
      ),
    ],
  );
});

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: MyApp()));
}

class MyApp extends ConsumerWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(goRouterProvider);
    return MaterialApp.router(
      title: 'RR Billing Pro',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      routerConfig: router,
    );
  }
}
