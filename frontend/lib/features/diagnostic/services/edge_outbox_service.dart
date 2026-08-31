import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../../../core/database/database_manager.dart';
import 'cloud_diagnostic_service.dart';

/// Outcome classes for edge-inference sync attempts.
enum _SyncOutcome { durable, retryable, permanent }

class EdgeOutboxService {
  final _cloudService = CloudDiagnosticService();
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  bool _draining = false; // Prevents concurrent drain runs

  /// Starts listening for connectivity changes.
  /// Call this once at app startup (e.g., after login).
  void startListening() {
    _connectivitySub?.cancel();
    _connectivitySub = Connectivity().onConnectivityChanged.listen((results) {
      final hasInternet = !results.contains(ConnectivityResult.none);
      if (hasInternet) {
        final userId = Supabase.instance.client.auth.currentUser?.id;
        if (userId != null) {
          drainOutbox(userId);
        }
      }
    });
    debugPrint('[Outbox] 📡 Connectivity listener started.');
  }

  /// Stops the connectivity listener. Call on logout or dispose.
  void stopListening() {
    _connectivitySub?.cancel();
    _connectivitySub = null;
    debugPrint('[Outbox] 📡 Connectivity listener stopped.');
  }

  /// Drains pending edge scans by uploading them to /sync/edge-inference.
  ///
  /// Three outcome classes (per backend contract):
  ///   1. Durable  — 200/409 with non-null `storage_path` → delete local file, clear queue.
  ///   2. Retryable — any 5xx (incl. 503 storage_upload_failed) → keep file, back off, retry.
  ///   3. Permanent — 413 (oversize, 25 MB cap) or 422 (bad payload / scan_id_conflict)
  ///                  → keep file, STOP retrying, surface to user.
  ///
  /// The delete rule: delete the local file ONLY when the response body contains
  /// a non-null `storage_path`.
  Future<void> drainOutbox(String userId) async {
    // Guard against concurrent runs
    if (_draining) return;
    _draining = true;

    try {
      final db = DatabaseManager.drift;
      final pending = await db.getPendingScans();

      if (pending.isEmpty) {
        debugPrint('[Outbox] No pending edge scans to sync.');
        return;
      }

      debugPrint('[Outbox] Draining ${pending.length} edge scan(s)...');

      for (final scan in pending) {
        try {
          await db.updateScanSyncStatus((scan.scanId ?? scan.id), 'uploading');

          final imageFile = File(scan.imageUrl ?? '');
          if (!imageFile.existsSync()) {
            debugPrint('[Outbox] Image file missing for scan ${(scan.scanId ?? scan.id)}. Marking failed.');
            await db.updateScanSyncStatus((scan.scanId ?? scan.id), 'failed');
            continue;
          }

          final cloudResponse = await _cloudService.syncEdgeInference(
            imageFile: imageFile,
            scanId: (scan.scanId ?? scan.id),
            scanType: scan.scanType,
            scanStatus: scan.scanStatus,
            aiDiagnosis: scan.aiDiagnosis ?? 'Analyzed',
            confidence: scan.confidence ?? 0.0,
            modality: scan.modality ?? 'cxr',
            patientId: scan.userId,
            findings: scan.findings,
            metadata: scan.metadata,
          );

          if (cloudResponse == null) {
            // Network-level failure (no response at all) — retryable
            await db.updateScanSyncStatus((scan.scanId ?? scan.id), 'pending');
            continue;
          }

          final statusCode = cloudResponse.statusCode;
          Map<String, dynamic>? body;
          try {
            body = jsonDecode(cloudResponse.body) as Map<String, dynamic>?;
          } catch (_) {
            body = null;
          }

          final outcome = _classifyOutcome(statusCode);
          final storagePath = body?['storage_path'] as String?;
          final errorCode = body?['code'] as String?;

          switch (outcome) {
            case _SyncOutcome.durable:
              await db.updateScanSyncStatus((scan.scanId ?? scan.id), 'synced');
              debugPrint('[Outbox] ✅ Scan ${(scan.scanId ?? scan.id)} synced (Status: $statusCode)');

              // THE DELETE RULE: only delete the local file when storage_path is non-null.
              if (storagePath != null && imageFile.existsSync()) {
                imageFile.deleteSync();
                debugPrint('[Outbox] 🗑️ Deleted local file for ${(scan.scanId ?? scan.id)} (storage_path confirmed: $storagePath)');
              } else {
                debugPrint('[Outbox] ⚠️ Keeping local file for ${(scan.scanId ?? scan.id)} — storage_path was null despite $statusCode');
              }
              break;

            case _SyncOutcome.retryable:
              // 5xx including 503 storage_upload_failed — keep the file, retry later.
              await db.updateScanSyncStatus((scan.scanId ?? scan.id), 'pending');
              debugPrint('[Outbox] ⚠️ Retryable error for ${(scan.scanId ?? scan.id)} (Status: $statusCode, code: $errorCode). Will retry.');
              break;

            case _SyncOutcome.permanent:
              // 413 or 422 — stop retrying. Surface to user.
              await db.updateScanSyncStatus((scan.scanId ?? scan.id), 'rejected');

              String reason;
              if (statusCode == 413) {
                reason = 'Image exceeds the 25 MB upload limit.';
              } else if (errorCode == 'scan_id_conflict') {
                reason = 'This scan ID already belongs to another user\'s record.';
              } else {
                reason = 'Server rejected the upload (code: ${errorCode ?? 'unknown'}).';
              }

              debugPrint('[Outbox] ❌ PERMANENT failure for ${(scan.scanId ?? scan.id)}: $reason');
              debugPrint('[Outbox] ❌ Full 422 response body: ${cloudResponse.body}');
              // Store the rejection reason in metadata so the UI can surface it.
              final existingMeta = scan.metadata;
              Map<String, dynamic> meta = {};
              if (existingMeta != null && existingMeta.isNotEmpty) {
                try {
                  meta = jsonDecode(existingMeta) as Map<String, dynamic>;
                } catch (_) {}
              }
              meta['rejection_reason'] = reason;
              meta['rejected_at'] = DateTime.now().toIso8601String();
              await db.customStatement(
                'UPDATE scan_results SET metadata = ? WHERE scan_id = ?',
                [jsonEncode(meta), (scan.scanId ?? scan.id)],
              );
              break;
          }
        } catch (e) {
          debugPrint('[Outbox] ❌ Error syncing scan ${(scan.scanId ?? scan.id)}: $e');
          await DatabaseManager.drift.updateScanSyncStatus((scan.scanId ?? scan.id), 'pending');
        }
      }
    } finally {
      _draining = false;
    }
  }

  /// Classifies HTTP status codes into the three outcome classes.
  static _SyncOutcome _classifyOutcome(int statusCode) {
    if (statusCode == 200 || statusCode == 409) return _SyncOutcome.durable;
    if (statusCode == 413 || statusCode == 422) return _SyncOutcome.permanent;
    // Everything else (5xx, unexpected 4xx) is retryable
    return _SyncOutcome.retryable;
  }
}
