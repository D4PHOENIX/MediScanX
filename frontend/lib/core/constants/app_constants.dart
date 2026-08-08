import '../config/env_config.dart';

class AppConstants{

  // App info
  static const String appName = 'MediScanX';
  static const String appVersion = '1.0.0';

  // Database
  static const String databaseFileName = 'mediscanx.db';

  // API Endpoints
  static String get baseUrl => EnvConfig.apiBaseUrl;

  // Timeouts
  static const Duration apiTimeout = Duration(seconds: 30);
  static const Duration databaseTimeout = Duration(seconds: 10);

  // Cache Duration
  static const Duration cacheDuration = Duration(hours: 24);

}