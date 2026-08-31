import 'dart:async';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'package:mediscanx_mobile/features/auth/screens/password_reset_screen.dart';
import 'package:mediscanx_mobile/features/auth/screens/register_screen.dart';
import 'package:mediscanx_mobile/features/auth/screens/splash_screen.dart';
import 'package:mediscanx_mobile/features/dashboard/screens/dashboard_screen.dart';
import '../features/auth/screens/login_screen.dart';
import '../features/chat/screens/ai_chat_screen.dart';
import '../features/diagnostic/screens/diagnostic_result_screen.dart';
import '../features/diagnostic/screens/diagnostic_screen.dart';
import '../features/referral/screens/referral_package_screen.dart';

final appRouter = GoRouter(
  initialLocation: '/',

  // 1. Trigger router rebuilds the exact moment auth state changes
  refreshListenable: GoRouterRefreshStream(
    Supabase.instance.client.auth.onAuthStateChange,
  ),

  routes: [
    GoRoute(
      path: '/',
      name: 'splash',
      builder: (context, state) => const SplashScreen(),
    ),
    GoRoute(
      path: '/login',
      name: 'login',
      builder: (context, state) => const LoginScreen(),
    ),
    GoRoute(
      path: '/register',
      name: 'register',
      builder: (context, state) => const RegisterScreen(),
    ),
    GoRoute(
      path: '/password-reset',
      name: 'password-reset',
      builder: (context, state) => const PasswordResetScreen(),
    ),
    GoRoute(
      path: '/dashboard',
      name: 'dashboard',
      builder: (context, state) => const DashboardScreen(),
    ),
    GoRoute(
      path: '/diagnostic',
      name: 'diagnostic',
      builder: (context, state) => const DiagnosticScreen(),
    ),
    GoRoute(
      path: '/diagnostic-result/:module',
      name: 'diagnostic_result',
      builder: (context, state) {
        final moduleName = state.pathParameters['module'] ?? 'Chest X-Ray';
        return DiagnosticResultScreen(activeModule: moduleName);
      }
    ),
    GoRoute(
      path: '/ai-chat',
      name: 'ai_chat',
      builder: (context, state) => const AIChatScreen(),
    ),
    GoRoute(
      path: '/referral-package',
      name: 'referral',
      builder: (context, state) => const ReferralPackageScreen(),
    ),
  ],

  // 2. The Gatekeeper Logic
  redirect: (context, state) {
    // Check if there is an active session stored on the device
    final session = Supabase.instance.client.auth.currentSession;
    final isLoggedIn = session != null;

    // Define which pages don't require an account
    // Note: We treat the Splash screen ('/') as an auth page here so
    // logged-in users bypass it entirely on app launch.
    final isAuthPage = state.matchedLocation == '/login' ||
        state.matchedLocation == '/register' ||
        state.matchedLocation == '/password-reset' ||
        state.matchedLocation == '/';

    // SCENARIO 1: Not logged in, trying to reach a secure page (like dashboard)
    if (!isLoggedIn && !isAuthPage) {
      return '/login'; // Kick them back to login
    }

    // SCENARIO 2: Logged in, but trying to view login/splash screens
    if (isLoggedIn && isAuthPage) {
      return '/dashboard'; // Send them straight into the app
    }

    // Return null means "proceed to the requested route normally"
    return null;
  },
);

// ==========================================
// UTILITY: STREAM TO LISTENABLE CONVERTER
// ==========================================
// GoRouter requires a 'Listenable' to trigger refreshes, but Supabase provides a 'Stream'.
// This class bridges that gap so GoRouter can hear Supabase's announcements.
class GoRouterRefreshStream extends ChangeNotifier {
  GoRouterRefreshStream(Stream<dynamic> stream) {
    notifyListeners();
    _subscription = stream.asBroadcastStream().listen(
          (dynamic _) => notifyListeners(),
    );
  }

  late final StreamSubscription<dynamic> _subscription;

  @override
  void dispose() {
    _subscription.cancel();
    super.dispose();
  }
}