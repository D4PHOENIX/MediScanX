// lib/core/database/database_manager.dart
import 'package:powersync/powersync.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:flutter/foundation.dart' show kIsWeb, debugPrint;
import 'package:drift_sqlite_async/drift_sqlite_async.dart';
import 'powersync_schema.dart';
import 'supabase_connector.dart';
import '../config/env_config.dart';
import '../config/drift_database.dart';

class DatabaseManager {
  static PowerSyncDatabase? _powersync;
  static AppDatabase? _drift;

  static PowerSyncDatabase get powersync {
    if(_powersync == null) throw Exception("PowerSync not initialized. Call DatabaseManager.initialize() first.");
    return _powersync!;
  }
  static AppDatabase get drift{
    if(_drift == null) throw Exception("Drift not initialized. Call DatabaseManager.initialize() first.");
    return _drift!;
  }

  static Future<void> initialize() async {
    try {
      String dbPath;
      if (kIsWeb) {
        dbPath = 'mediscanx_final_v2.db';
      } else {
        final dir = await getApplicationDocumentsDirectory();
        dbPath = p.join(dir.path, 'mediscanx_final_v2.db');
      }

      final ps = PowerSyncDatabase(schema: appSchema, path: dbPath);
      await ps.initialize();
      // 1. Initialize PowerSync
      _powersync = ps;

      // 2. Initialize Drift using PowerSync's internal SQLite connection
      // This is the most stable way to bridge them without manual code
      _drift = AppDatabase(SqliteAsyncDriftConnection(ps));

      // 3. Setup Connector
      final connector = SupabaseConnector(
        supabase: Supabase.instance.client,
        powerSyncUrl: EnvConfig.powerSyncUrl,
      );

      // 4. Connect
      ps.connect(connector: connector);
      debugPrint("🟢 Database initialized successfully.");
    } catch (e) {
      debugPrint("🔴 Database Init Failed: $e");
      rethrow; // This will show the error in your console instead of just a black screen
    }
  }
}