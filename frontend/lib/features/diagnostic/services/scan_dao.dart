import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:drift/drift.dart';
import 'package:mediscanx_mobile/core/config/drift_database.dart';
import 'package:mediscanx_mobile/core/config/env_config.dart';
import 'package:mediscanx_mobile/features/diagnostic/models/diagnostic_result.dart';

class ScanDao {
  final AppDatabase db;
  ScanDao(this.db);

  // Helper to map String types to Supabase integers
  int _mapScanTypeToInt(String type) {
    if (type.contains('Chest')) return 0;
    if (type.contains('ECG')) return 1;
    if (type.contains('Skin')) return 2;
    return 0; // Fallback
  }

  // Helper to map String types to Supabase modality string
  String _mapScanTypeToModality(String type) {
    if (type.contains('Chest')) return 'cxr';
    if (type.contains('ECG')) return 'ecg';
    if (type.contains('Skin')) return 'skin';
    return 'cxr'; // Fallback
  }

  // Helper to map risk levels to Supabase integers
  int _mapStatusToInt(bool isRedAlert, double confidence) {
    if (isRedAlert) return 2; // High Risk
    if (confidence > 0.5) return 1; // Moderate
    return 0; // Normal
  }

  Future<void> insertScan(DiagnosticResult result, String userId) async {
    final metadataJson = jsonEncode({
      'aiModel': result.aiModel,
      'method': result.method,
      'isRedAlert': result.isRedAlert,
      'scan_status': result.scanStatus,
      'tags': result.tags,
      'findings': result.findings.map((f) => f.toJson()).toList(),
    });

    // 🔴 THE FIX: Use Drift's safe Companion insertion to handle DateTime/String mapping correctly
    await db.into(db.scanResults).insert(
      ScanResultsCompanion.insert(
        id: result.id,
        scanId: Value(result.id),
        userId: userId,
        scanType: _mapScanTypeToInt(result.scanType),
        modality: Value(_mapScanTypeToModality(result.scanType)),
        scanStatus: result.scanStatus,
        imageUrl: Value(result.imagePath),
        aiDiagnosis: Value(result.tags.isNotEmpty ? result.tags.first : 'Analyzed'),
        findings: Value(result.recommendation),
        confidence: Value(result.overallConfidence),
        metadata: Value(metadataJson),
        scanDate: result.scanDate,
        createdAt: result.scanDate,
        updatedAt: result.scanDate,
        syncStatus: const Value('pending'),
      ),
      mode: InsertMode.insertOrReplace,
    );
  }

  /// Updates an existing local scan record with the authoritative cloud scan_id and image_url.
  /// Called by EdgeOutboxService after a successful cloud upload of an edge scan.
  Future<void> updateScanWithCloudData({
    required String localId,
    required String cloudScanId,
    required String imageUrl,
  }) async {
    await db.customStatement(
      'UPDATE scan_results SET scan_id = ?, image_url = ?, sync_status = ? WHERE id = ?',
      [cloudScanId, imageUrl, 'synced', localId],
    );
  }

  /// Fetches the most recent scan by type (0 = CXR, 1 = ECG, 2 = Skin) for the user
  Future<ScanResult?> getLatestScanByType(int scanType, String userId) async {
    try {
      return await (db.select(db.scanResults)
            ..where((t) => t.userId.equals(userId))
            ..where((t) => t.scanType.equals(scanType))
            ..orderBy([
              (t) => OrderingTerm(expression: t.scanDate, mode: OrderingMode.desc)
            ])
            ..limit(1))
          .getSingleOrNull();
    } catch (e, stackTrace) {
      // Catch mapping errors (like Null check operator) caused by local DB corruption
      debugPrint('🔴 getLatestScanByType ERROR for scanType=$scanType: $e');
      
      // Dump raw row to see which non-nullable column is NULL
      try {
        final rawRows = await db.customSelect(
          'SELECT * FROM scan_results WHERE user_id = ? AND scan_type = ? ORDER BY scan_date DESC LIMIT 1',
          variables: [Variable.withString(userId), Variable.withInt(scanType)],
        ).get();
        for (var row in rawRows) {
          debugPrint('RAW ROW DATA for scanType=$scanType: ${row.data}');
        }
      } catch (innerE) {
        debugPrint('Failed to dump raw row: $innerE');
      }
      
      return null;
    }
  }
}