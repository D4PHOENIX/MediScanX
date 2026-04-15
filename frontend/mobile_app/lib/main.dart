import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:go_router/go_router.dart';

// --- DATABASE & CORE IMPORTS ---
import 'core/config/env_config.dart';
import 'core/database/database_manager.dart';

// --- FEATURE SCREEN IMPORTS ---
import 'package:mediscanx_mobile/features/diagnostic/screens/diagnostic_screen.dart';
import 'package:mediscanx_mobile/features/auth/screens/splash_screen.dart';
import 'package:mediscanx_mobile/features/auth/screens/login_screen.dart';
import 'package:mediscanx_mobile/features/auth/screens/register_screen.dart';
import 'package:mediscanx_mobile/features/auth/screens/password_reset_screen.dart';
import 'package:mediscanx_mobile/features/dashboard/screens/dashboard_screen.dart';
import 'features/chat/screens/ai_chat_screen.dart';
import 'features/diagnostic/screens/diagnostic_result_screen.dart';
import 'features/referral/screens/referral_package_screen.dart';
import 'features/debug/screens/sync_debug_screen.dart';

// ==========================================
// MAIN ENTRY POINT
// ==========================================

void main() async {
  // 1. Ensure Flutter bindings are ready
  WidgetsFlutterBinding.ensureInitialized();

  try{
    // 2. Load environment variables from .env
    await dotenv.load(fileName: '.env');

    // 3. Initialize Supabase
    await Supabase.initialize(
      url: EnvConfig.supabaseUrl,
      anonKey: EnvConfig.supabaseAnonKey,
    );

    // 4. Start the PowerSync Offline Engine & Drift Database
    // This handles path configuration, syncing, and local storage setup
    await DatabaseManager.initialize();
  } catch (e){
    debugPrint("🔴 CRITICAL INIT ERROR: $e");
  }

  // 5. Wrap the app in ProviderScope to enable Riverpod
  runApp(
    const ProviderScope(
      child: MediScanXApp(),
    ),
  );
}

class MediScanXApp extends ConsumerWidget {
  const MediScanXApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);

    return MaterialApp.router(
      title: 'MediScanX',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
        useMaterial3: true,
      ),
      routerConfig: router,
    );
  }
}

// ==========================================
// GO ROUTER CONFIGURATION & AUTH GUARD
// ==========================================

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/',

    // Trigger router rebuilds when auth state changes (Login/Logout)
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
      GoRoute(
        path: '/sync-debug',
        name: 'sync_debug',
        builder: (context, state) => const SyncDebugScreen(),
      ),
    ],

    // Redirect logic to protect private routes
    redirect: (context, state) {
      final session = Supabase.instance.client.auth.currentSession;
      final isLoggedIn = session != null;

      final isPublicPage = state.matchedLocation == '/login' ||
          state.matchedLocation == '/register' ||
          state.matchedLocation == '/password-reset' ||
          state.matchedLocation == '/';

      if (!isLoggedIn && !isPublicPage) {
        return '/login';
      }

      // Keep password-reset accessible when recovering via email deep links.
      final shouldRedirectLoggedInToDashboard =
          state.matchedLocation == '/' ||
              state.matchedLocation == '/login' ||
              state.matchedLocation == '/register';

      if (isLoggedIn && shouldRedirectLoggedInToDashboard) {
        return '/dashboard';
      }

      return null;
    },
  );
});

// ==========================================
// UTILITY: STREAM TO LISTENABLE CONVERTER
// ==========================================
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