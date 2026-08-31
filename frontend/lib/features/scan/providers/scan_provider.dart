// lib/features/diagnostic/providers/scan_provider.dart
import 'dart:async';
import 'dart:io';

import 'package:mediscanx_mobile/features/diagnostic/models/diagnostic_result.dart';
import 'package:mediscanx_mobile/features/diagnostic/services/scan_dao.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:riverpod_annotation/riverpod_annotation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

// 🔴 THE FIX: Import the unified DiagnosticResult model and correct the relative paths
import 'package:mediscanx_mobile/core/database/database_manager.dart';

part 'scan_provider.g.dart';

@riverpod
class ScanState extends _$ScanState {
  late final ScanDao _scanDao;

  @override
  FutureOr<DiagnosticResult?> build() {
    _scanDao = ScanDao(DatabaseManager.drift);
    return null; // Initial state: no active scan
  }

  // Helper to grab the active user
  String get _currentUserId =>
      Supabase.instance.client.auth.currentUser?.id ?? "anonymous_user";

  /// Permanently saves the gallery image to the app's local storage
  Future<String> _secureLocalImage(String originalGalleryPath) async {
    final directory = await getApplicationDocumentsDirectory();
    final fileName = p.basename(originalGalleryPath);
    // Create a unique name so we don't overwrite previous scans
    final uniqueFileName = '${DateTime.now().millisecondsSinceEpoch}_$fileName';
    final savedImagePath = p.join(directory.path, uniqueFileName);

    // Copy the file
    final originalFile = File(originalGalleryPath);
    final savedFile = await originalFile.copy(savedImagePath);

    return savedFile.path;
  }

  /// Entry point for running TFLite inference
  Future<void> runInference(String originalImagePath) async {
    state = const AsyncLoading();

    // 🔴 THE FIX: Type the guard container as <DiagnosticResult?> to match the new state
    state = await AsyncValue.guard<DiagnosticResult?>(() async {
      // 1. Secure the image so it doesn't break offline later
      final permanentImagePath = await _secureLocalImage(originalImagePath);

      // 2. TODO: TFLite Model Loading & Processing
      await Future.delayed(const Duration(seconds: 3)); // Mock delay

      // 3. Generate the Unified Data Result
      final result = DiagnosticResult(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        scanDate: DateTime.now(),
        imagePath: permanentImagePath,
        scanType: 'Chest X-Ray', // Matches your module configurations
        aiModel: 'DenseNet-121',
        method: 'Grad-CAM++',
        overallConfidence: 0.985,
        isRedAlert: false,
        tags: ['Clear Fields'],
        findings: [
          AIFinding(
            region: 'Lung Fields',
            observation: 'Normal lucency, no infiltrates or effusions detected.',
            riskLevel: 'Normal',
            confidence: 0.99,
          ),
        ],
        recommendation: 'No acute abnormalities detected in the current scan.',
        xai: null,
      );

      // 4. Save to SQLite (PowerSync watches this table to sync to Supabase)
      await _scanDao.insertScan(result, _currentUserId);

      return result;
    });
  }

  void reset() {
    state = const AsyncData(null);
  }
}