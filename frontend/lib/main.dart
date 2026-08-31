import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:app_links/app_links.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:go_router/go_router.dart';
import 'package:dio/dio.dart';
import 'package:url_launcher/url_launcher.dart';
import 'features/triage/services/triage_api_service.dart';

// --- NETWORK & CORE CONFIG IMPORTS ---
import 'package:mediscanx_mobile/core/network/api_client.dart';
import 'package:mediscanx_mobile/core/config/env_config.dart';

// --- DATABASE, ENGINES & CORE IMPORTS ---
import 'package:mediscanx_mobile/core/database/database_manager.dart';
import 'package:mediscanx_mobile/core/ml/cxr_tflite_engine.dart';
import 'package:mediscanx_mobile/core/ml/skin_tflite_engine.dart';

// --- FEATURE MODELS ---
import 'package:mediscanx_mobile/features/diagnostic/models/diagnostic_result.dart';
import 'package:mediscanx_mobile/features/diagnostic/models/fusion_models.dart';

// --- FEATURE SCREEN IMPORTS (STRICTLY PATH INDEPENDENT PACKAGE PATHS) ---
import 'package:mediscanx_mobile/features/auth/screens/splash_screen.dart';
import 'package:mediscanx_mobile/features/auth/screens/login_screen.dart';
import 'package:mediscanx_mobile/features/auth/screens/register_screen.dart';
import 'package:mediscanx_mobile/features/auth/screens/password_reset_screen.dart';
import 'package:mediscanx_mobile/features/dashboard/screens/dashboard_screen.dart';
import 'package:mediscanx_mobile/features/dashboard/screens/temporal_tracking_screen.dart';
import 'package:mediscanx_mobile/features/dashboard/screens/temporal_selection_screen.dart';
import 'package:mediscanx_mobile/features/diagnostic/screens/diagnostic_screen.dart';
import 'package:mediscanx_mobile/features/diagnostic/screens/diagnostic_result_screen.dart';
import 'package:mediscanx_mobile/features/diagnostic/screens/fusion_result_screen.dart';
import 'package:mediscanx_mobile/features/diagnostic/presentation/skin_diagnostic_screen.dart';
import 'package:mediscanx_mobile/features/chat/screens/ai_chat_screen.dart';
import 'package:mediscanx_mobile/features/chat/models/ai_chat_args.dart';
import 'package:mediscanx_mobile/features/referral/screens/referral_package_screen.dart';
import 'package:mediscanx_mobile/features/debug/screens/sync_debug_screen.dart';
import 'package:mediscanx_mobile/features/triage/screens/triage_dashboard_screen.dart';
import 'package:mediscanx_mobile/features/referral/screens/care_relationships_screen.dart';
import 'package:mediscanx_mobile/features/dashboard/screens/temporal_tracking_screen.dart';
import 'package:mediscanx_mobile/features/diagnostic/services/edge_outbox_service.dart';
import 'package:mediscanx_mobile/features/downloads/screens/downloads_screen.dart';

// ==========================================
// MAIN ENTRY POINT
// ==========================================

String _initialRoute = '/';
bool _suppressLoginRedirect = false;

void armLoginRedirectSuppression() {
  _suppressLoginRedirect = true;
  Future.delayed(const Duration(seconds: 3), () {
    _suppressLoginRedirect = false;
  });
}

bool _isMailDeepLink(Uri? uri) {
  if (uri == null || uri.scheme.toLowerCase() != 'mediscanx') {
    return false;
  }
  return uri.host.isNotEmpty || uri.path.isNotEmpty;
}

String _deepLinkRoute(Uri? uri) {
  final host = uri?.host.toLowerCase() ?? '';
  if (host == 'password-reset') {
    return '/password-reset';
  }
  if (host == 'login') {
    return '/login';
  }
  return '/login';
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  ErrorWidget.builder = (details) {
    return Directionality(
        textDirection: TextDirection.ltr,
        child: Material(
          color: Colors.white,
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                'Something went wrong. Please restart the app.\n\n${details.exceptionAsString()}',
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.red),
              ),
            ),
          ),
        )
    );
  };

  FlutterError.onError = (details) {
    FlutterError.presentError(details);
    debugPrint('❌ FlutterError: ${details.exceptionAsString()}');
  };

  try {
    await dotenv.load(fileName: '.env');

    await Supabase.initialize(
      url: EnvConfig.supabaseUrl,
      anonKey: EnvConfig.supabaseAnonKey,
    );

    await DatabaseManager.initialize();
    await TFLiteEngine().loadModel();
    await SkinTfliteEngine().loadModel();

    try {
      final initialUri = await AppLinks().getInitialLink();
      debugPrint('🔗 Initial deep link (pre-runApp): $initialUri');
      if (_isMailDeepLink(initialUri)) {
        _initialRoute = _deepLinkRoute(initialUri);
        if (_initialRoute == '/login') {
          armLoginRedirectSuppression();
        }
        debugPrint('✅ Initial route set to $_initialRoute');
      }
    } catch (e) {
      debugPrint('❌ Error resolving initial deep link before runApp: $e');
    }
  } catch (e) {
    debugPrint("🔴 CRITICAL INIT ERROR: $e");
  }

  runApp(
    const ProviderScope(
      child: MediScanXApp(),
    ),
  );
}

class MediScanXApp extends ConsumerStatefulWidget {
  const MediScanXApp({super.key});

  @override
  ConsumerState<MediScanXApp> createState() => _MediScanXAppState();
}

class _MediScanXAppState extends ConsumerState<MediScanXApp> {
  final AppLinks _appLinks = AppLinks();
  StreamSubscription<Uri?>? _linkSubscription;
  StreamSubscription<AuthState>? _authSubscription;
  final EdgeOutboxService _outboxService = EdgeOutboxService();

  @override
  void initState() {
    super.initState();
    _initDeepLinks();
    _initOutboxService();
  }

  /// Starts the outbox connectivity listener if the user is already logged in,
  /// and listens for auth state changes to start/stop it on login/logout.
  void _initOutboxService() {
    // If user is already logged in at app start, begin listening immediately.
    final currentUser = Supabase.instance.client.auth.currentUser;
    if (currentUser != null) {
      _outboxService.startListening();
    }

    // React to login/logout events.
    _authSubscription = Supabase.instance.client.auth.onAuthStateChange.listen((data) {
      if (data.event == AuthChangeEvent.signedIn) {
        _outboxService.startListening();
      } else if (data.event == AuthChangeEvent.signedOut) {
        _outboxService.stopListening();
      }
    });
  }

  Future<void> _initDeepLinks() async {
    final router = ref.read(routerProvider);

    _linkSubscription = _appLinks.uriLinkStream.listen(
          (uri) async {
        debugPrint('🔗 Runtime deep link received: $uri');
        await _handleDeepLink(uri, router);
      },
      onError: (Object error) {
        debugPrint('❌ Deep link stream error: $error');
      },
    );
  }

  Future<void> _handleDeepLink(Uri? uri, GoRouter router) async {
    if (uri == null) return;



    if (uri.scheme.toLowerCase() != 'mediscanx') return;

    if (_isMailDeepLink(uri)) {
      final route = _deepLinkRoute(uri);
      try {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) {
            if (route == '/login') {
              armLoginRedirectSuppression();
            }
            router.goNamed(route.substring(1));

            Future.delayed(const Duration(seconds: 2), () {
              final currentUri = router.routeInformationProvider.value.uri;
              if (mounted && currentUri.path == '/') {
                armLoginRedirectSuppression();
                router.goNamed('login');
              }
            });
          }
        });
      } catch (e) {
        debugPrint('❌ Navigation error: $e');
      }
    }
  }
  
  @override
  void dispose() {
    _linkSubscription?.cancel();
    _authSubscription?.cancel();
    _outboxService.stopListening();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
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
// DEEP LINK SCREENS
// ==========================================

class ClaimProcessingScreen extends StatefulWidget {
  final Uri uri;
  const ClaimProcessingScreen({super.key, required this.uri});

  @override
  State<ClaimProcessingScreen> createState() => _ClaimProcessingScreenState();
}

class _ClaimProcessingScreenState extends State<ClaimProcessingScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _process();
    });
  }

  Future<void> _process() async {
    final token = widget.uri.queryParameters['token'];
    if (token == null || token.isEmpty) {
      if (mounted) context.goNamed('dashboard');
      return;
    }

    final service = TriageApiService();
    final result = await service.claimScan(token);

    if (result == null) {
      if (mounted) {
        await showDialog(
          context: context,
          builder: (_) => AlertDialog(
            title: const Text('Invalid Link'),
            content: const Text('This scan link is invalid or has expired.'),
            actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
          ),
        );
        if (mounted) context.goNamed('dashboard');
      }
      return;
    }

    final reportUrl = result['report_url']?.toString();
    if (reportUrl != null && reportUrl.isNotEmpty) {
      final parsedUri = Uri.parse(reportUrl);
      if (await canLaunchUrl(parsedUri)) {
        await launchUrl(parsedUri, mode: LaunchMode.externalApplication);
      }
    }

    if (result['access_granted'] == true && mounted) {
      final expiresAtStr = result['access_expires_at']?.toString();
      if (expiresAtStr != null) {
        final dt = DateTime.tryParse(expiresAtStr)?.toLocal();
        if (dt != null) {
          final formattedDate = '${dt.day}/${dt.month}/${dt.year} at ${dt.hour}:${dt.minute.toString().padLeft(2, '0')}';
          await showDialog(
            context: context,
            builder: (_) => AlertDialog(
              title: const Text('Access Granted'),
              content: Text('You have been granted access to this patient\'s records until $formattedDate.'),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('OK'),
                )
              ],
            ),
          );
        }
      }
      if (mounted) context.goNamed('triage');
    } else if (result['access_granted'] == false && mounted) {
      final reason = result['reason']?.toString();
      if (reason != null && reason.isNotEmpty) {
        String message = 'Access to this patient\'s triage history was not granted.';
        if (reason.toLowerCase() == 'revoked') {
          message = 'The patient has revoked your access to their triage history.';
        } else if (reason.toLowerCase() == 'declined') {
          message = 'The patient declined to grant access.';
        } else {
          message = '$message Reason: $reason';
        }

        await showDialog(
          context: context,
          builder: (_) => AlertDialog(
            title: const Text('Access Declined'),
            content: Text(message),
            actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
          ),
        );
      }
      if (mounted) context.goNamed('dashboard');
    }
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 24),
            Text('Processing your claim...', style: TextStyle(fontSize: 16)),
          ],
        ),
      ),
    );
  }
}

// ==========================================
// GO ROUTER CONFIGURATION & AUTH GUARD
// ==========================================

final navigatorKey = GlobalKey<NavigatorState>();

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    navigatorKey: navigatorKey,
    initialLocation: _initialRoute,
    errorBuilder: (context, state) {
      return Scaffold(
        backgroundColor: Colors.white,
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(
              'Navigation error:\n${state.error}',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.red),
            ),
          ),
        ),
      );
    },

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
        path: '/claim',
        name: 'claim',
        builder: (context, state) {
          return ClaimProcessingScreen(uri: state.uri);
        },
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
        path: '/temporal-selection',
        name: 'temporal_selection',
        builder: (context, state) => const TemporalSelectionScreen(),
      ),
      GoRoute(
        path: '/temporal-tracking/:modality',
        name: 'temporal_tracking',
        builder: (context, state) {
          final modality = state.pathParameters['modality'] ?? 'cxr';
          return TemporalTrackingScreen(modality: modality);
        },
      ),
      GoRoute(
        path: '/diagnostic',
        name: 'diagnostic',
        builder: (context, state) => const DiagnosticScreen(),
      ),
      /*GoRoute(
        path: '/care-relationships',
        name: 'care_relationships',
        builder: (context, state) => const CareRelationshipsScreen(),
      ),*/
      GoRoute(
        path: '/fusion-result',
        name: 'fusion_result',
        builder: (context, state) {
          final fusionData = state.extra as FusionResponse;
          return FusionResultScreen(fusionData: fusionData);
        },
      ),
      GoRoute(
        path: '/skin-diagnostic',
        name: 'skin_diagnostic',
        builder: (context, state) => const SkinDiagnosticScreen(),
      ),
      GoRoute(
          path: '/diagnostic-result/:module',
          name: 'diagnostic_result',
          builder: (context, state) {
            final moduleName = state.pathParameters['module'] ?? 'Chest X-Ray';
            final extraData = state.extra as DiagnosticResult?;

            return DiagnosticResultScreen(
              activeModule: moduleName,
              offlineResult: extraData,
            );
          }
      ),
      GoRoute(
        path: '/ai-chat',
        name: 'ai_chat',
        builder: (context, state) {
          final extraData = state.extra;
          if (extraData is AIChatArgs) {
            return AIChatScreen(
              preloadedResult: extraData.preloadedResult,
              scanContextId: extraData.scanContextId,
              initialPrompt: extraData.initialPrompt,
            );
          } else if (extraData is DiagnosticResult) {
            // Backwards compatibility
            return AIChatScreen(preloadedResult: extraData);
          }
          return const AIChatScreen();
        },
      ),
      GoRoute(
        path: '/downloads',
        name: 'downloads',
        builder: (context, state) => const DownloadsScreen(),
      ),
      GoRoute(
        path: '/referral-package',
        name: 'referral',
        builder: (context, state) {
          final args = state.extra as Map<String, dynamic>?;
          return ReferralPackageScreen(
            patientId: args?['patientId'] as String?,
            scanIds: args?['scanIds'] as List<String>?,
          );
        },
      ),
      GoRoute(
        path: '/sync-debug',
        name: 'sync_debug',
        builder: (context, state) => const SyncDebugScreen(),
      ),
      GoRoute(
        path: '/triage',
        name: 'triage',
        builder: (context, state) => const TriageDashboardScreen(),
      ),
    ],

    redirect: (context, state) {
      final session = Supabase.instance.client.auth.currentSession;
      final isLoggedIn = session != null;

      final isPublicPage = state.matchedLocation == '/login' ||
          state.matchedLocation == '/register' ||
          state.matchedLocation == '/password-reset' ||
          state.matchedLocation == '/';

      final role = (Supabase.instance.client.auth.currentUser?.userMetadata?['role'] ??
          Supabase.instance.client.auth.currentUser?.userMetadata?['userType'])
          ?.toString()
          .toLowerCase();
      final isDoctor = role == 'doctor';

      if (!isLoggedIn && !isPublicPage) {
        return '/login';
      }

      final shouldRedirectLoggedInToDashboard =
          state.matchedLocation == '/' ||
              state.matchedLocation == '/login' ||
              state.matchedLocation == '/register';

      if (isLoggedIn && shouldRedirectLoggedInToDashboard) {
        if (_suppressLoginRedirect && state.matchedLocation == '/login') {
          return null;
        }
        return '/dashboard';
      }

      if (state.matchedLocation == '/triage' && !isDoctor) {
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