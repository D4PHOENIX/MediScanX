import 'package:dio/dio.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

class ApiConstants {
  // Cloudflare Zero Trust Tunnel Base URL
  static String get baseUrl => dotenv.env['API_BASE_URL'] ?? 'https://mediscanx.app/api/v1';}

class ApiClient {
  // Singleton pattern to support your existing `ApiClient()` calls
  static final ApiClient _instance = ApiClient._internal();
  late final Dio dio;

  // This allows your services to call `final ApiClient _apiClient = ApiClient();`
  factory ApiClient() {
    return _instance;
  }

  ApiClient._internal() {
    dio = Dio(
      BaseOptions(
        baseUrl: ApiConstants.baseUrl,
        // CRITICAL: 120-second timeout for LangGraph agent processing
        connectTimeout: const Duration(seconds: 120),
        receiveTimeout: const Duration(seconds: 120),
        // Prevent Dio from crashing the app on 400/500 errors
        validateStatus: (status) => status != null && status < 500,
      ),
    );

    // The Supabase Security Interceptor
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          // Grab the active Supabase token and attach it securely
          final session = Supabase.instance.client.auth.currentSession;
          if (session != null) {
            options.headers['Authorization'] = 'Bearer ${session.accessToken}';
          }
          return handler.next(options);
        },
        onError: (DioException e, handler) {
          debugPrint('🔴 MediScanX API Error: ${e.response?.statusCode} - ${e.message}');
          return handler.next(e);
        },
      ),
    );
  }

  // Keep this for Riverpod
  static Dio getClient() {
    return _instance.dio;
  }
}

// Global Riverpod Provider for the API Client
final dioProvider = Provider<Dio>((ref) {
  return ApiClient.getClient();
});

// Quick connection test to verify the Cloudflare tunnel is working
Future<void> testCloudConnection() async {
  try {
    final dio = ApiClient.getClient();
    debugPrint("🌐 Pinging the MediScanX Cloud...");
    final response = await dio.get('/health/healthz');
    debugPrint("✅ Success! The Cloud is alive: ${response.data}");
  } catch (e) {
    debugPrint("❌ Cloud Connection failed: $e");
  }
}