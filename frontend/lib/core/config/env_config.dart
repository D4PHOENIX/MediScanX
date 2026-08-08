import 'package:flutter_dotenv/flutter_dotenv.dart';

class EnvConfig {
  static String _required(String key) {
    final value = dotenv.env[key]?.trim();
    if (value == null || value.isEmpty) {
      throw Exception('Missing required environment variable: $key');
    }
    return value;
  }

  static String get supabaseUrl => _required('SUPABASE_URL');
  static String get supabaseAnonKey => _required('SUPABASE_ANON_KEY');
  static String get powerSyncUrl => _required('POWERSYNC_URL');

  // Non-sensitive API host can still be environment-specific.
  static String get apiBaseUrl =>
      dotenv.env['API_BASE_URL']?.trim().isNotEmpty == true
          ? dotenv.env['API_BASE_URL']!.trim()
          : 'https://api.mediscanx.com';
}

