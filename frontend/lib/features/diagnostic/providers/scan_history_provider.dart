// lib/features/diagnostic/providers/scan_history_provider.dart
import 'dart:convert';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:drift/drift.dart';

// --- STRICT PACKAGE IMPORTS ---
import 'package:mediscanx_mobile/core/database/database_manager.dart';
import 'package:mediscanx_mobile/features/diagnostic/services/scan_dao.dart';
import 'package:mediscanx_mobile/features/diagnostic/models/diagnostic_result.dart';
import 'package:mediscanx_mobile/core/config/env_config.dart';

/// Streams the user's scan history directly from the local SQLite database in real-time.
final userScanHistoryProvider = StreamProvider.family<List<DiagnosticResult>, String>((ref, userId) {
  final dao = ScanDao(DatabaseManager.drift);

  // The .watch() method creates a live stream.
  // When a new scan is inserted, the UI updates instantly.
  return dao.db.customSelect(
    'SELECT * FROM scan_results WHERE user_id = ? ORDER BY created_at DESC',
    variables: [Variable.withString(userId)],
    readsFrom: {dao.db.scanResults},
  ).watch().map((rows) {

    return rows.map((row) {
      final metadataString = row.read<String?>('metadata');
      Map<String, dynamic> meta = {};
      if (metadataString != null && metadataString.isNotEmpty) {
        try {
          var decoded = jsonDecode(metadataString);
          if (decoded is String) {
            decoded = jsonDecode(decoded);
          }
          if (decoded is Map<String, dynamic>) {
            meta = decoded;
          }
        } catch (_) {}
      }

      // Read findings from metadata (Edge scans) or from the dedicated findings column (Cloud scans)
      List<AIFinding> parsedFindings = [];
      var findingsData = meta['findings'] ?? meta['top_findings'];
      
      if (findingsData == null) {
        final findingsColStr = row.read<String?>('findings');
        if (findingsColStr != null && findingsColStr.isNotEmpty) {
          try {
            var decoded = jsonDecode(findingsColStr);
            if (decoded is String) decoded = jsonDecode(decoded);
            findingsData = decoded;
          } catch (_) {}
        }
      }

      if (findingsData != null && findingsData is List) {
        parsedFindings = findingsData.map((item) {
          // Fallbacks for snake_case vs camelCase keys
          final label = item['region'] ?? item['label'] ?? 'Unknown';
          final obs = item['observation'] ?? 'Cloud API Analysis';
          String risk = item['riskLevel'] ?? item['risk_level'] ?? 'Normal';
          if (item['riskLevel'] == null && item['risk_level'] == null && item.containsKey('scan_status')) {
            final statusVal = item['scan_status'];
            int? intStatus;
            if (statusVal is int) intStatus = statusVal;
            else if (statusVal is String) intStatus = int.tryParse(statusVal);
            
            if (intStatus == 2) risk = 'High';
            else if (intStatus == 1) risk = 'Moderate';
            else if (intStatus == 0) risk = 'Normal';
          }
          final conf = (item['confidence'] as num?)?.toDouble() ?? 0.0;
          
          // Historical data correction: If the finding is marked Normal but the overall scan is Warning/High Risk
          if (risk == 'Normal' && conf > 0.0) {
            final overallStatus = row.read<int?>('scan_status') ?? (meta['scan_status'] as int? ?? -1);
            if (overallStatus > 0) {
              final lowerLabel = label.toLowerCase();
              final isBenign = lowerLabel.contains('benign') || lowerLabel.contains('normal') || lowerLabel.contains('no finding') || lowerLabel == 'norm';
              if (!isBenign && conf >= 0.50) {
                risk = overallStatus == 2 ? 'High' : 'Moderate';
              }
            }
          }
          
          return AIFinding(region: label, observation: obs, riskLevel: risk, confidence: conf);
        }).toList().cast<AIFinding>();
      } 
      
      if (parsedFindings.isEmpty && meta['predictions'] != null && meta['predictions'] is Map) {
        // Fallback for ECG scans synced from cloud where `findings` might be stored as `predictions` map
        final predictionsRaw = meta['predictions'] as Map;
        predictionsRaw.forEach((key, value) {
          if (value is Map) {
            final isDetected = value['detected'] == true;
            if (isDetected) {
              final prob = (value['probability'] as num?)?.toDouble() ?? 0.0;
              final statusVal = value['scan_status'];
              int? scanStatusInt;
              if (statusVal is int) scanStatusInt = statusVal;
              else if (statusVal is String) scanStatusInt = int.tryParse(statusVal);
              
              String risk = 'Moderate';
              if (scanStatusInt != null) {
                if (scanStatusInt == 2) risk = 'High';
                else if (scanStatusInt == 1) risk = 'Moderate';
                else if (scanStatusInt == 0) risk = 'Normal';
              } else {
                final rawRisk = value['risk_level']?.toString().toUpperCase() ?? value['confidence']?.toString().toUpperCase();
                if (rawRisk != null) {
                  if (rawRisk == 'HIGH' || rawRisk == 'CRITICAL') risk = 'High';
                  else if (rawRisk == 'MODERATE' || rawRisk == 'WARNING') risk = 'Moderate';
                  else risk = 'Normal';
                }
              }
              parsedFindings.add(AIFinding(region: key.toString(), observation: 'Cloud API Analysis', riskLevel: risk, confidence: prob));
            }
          }
        });
      }

      final modalityStr = row.read<String?>('modality');
      String scanTypeStr;
      
      if (modalityStr != null && modalityStr.isNotEmpty) {
        final mod = modalityStr.toLowerCase();
        if (mod == 'cxr' || mod == 'x-ray') {
          scanTypeStr = 'Chest X-Ray';
        } else if (mod == 'ecg') {
          scanTypeStr = 'ECG';
        } else if (mod == 'skin') {
          scanTypeStr = 'Skin';
        } else {
          scanTypeStr = 'Chest X-Ray';
        }
      } else {
        // Fallback to legacy scan_type mapping if modality is missing
        final scanTypeInt = row.read<int?>('scan_type') ?? 0;
        scanTypeStr = 'Chest X-Ray';
        if (scanTypeInt == 1) scanTypeStr = 'ECG';
        if (scanTypeInt == 2) scanTypeStr = 'Skin';
      }

      final xaiStatus = row.read<String?>('xai_status') ?? meta['xai']?['status'] ?? 'not_requested';
      final xaiPath = row.read<String?>('xai_path');
      String? xaiUrl;
      if (xaiPath != null) {
        xaiUrl = '${EnvConfig.supabaseUrl}/storage/v1/object/authenticated/scan-images/$xaiPath';
      }

      // Retrieve scan status from db, fallback to meta, or derive from isRedAlert legacy logic
      int scanStatusInt = row.read<int?>('scan_status') ?? (meta['scan_status'] as int? ?? -1);

      // Derive Red Alert and Tags from findings if missing in meta
      bool isRedAlert = meta['isRedAlert'] ?? false;
      List<String> tags = List<String>.from(meta['tags'] ?? []);
      
      if (tags.isEmpty && parsedFindings.isNotEmpty) {
        for (var f in parsedFindings) {
          if (!tags.contains(f.region)) tags.add(f.region);
          if (f.riskLevel == 'HIGH' || f.riskLevel == 'CRITICAL') {
            isRedAlert = true;
          }
        }
      }

      // If backend explicitly marked it as High Risk (2), force red alert
      if (scanStatusInt == 2) {
        isRedAlert = true;
      } else if (isRedAlert && (scanStatusInt == 0 || scanStatusInt == -1)) {
        // Fallback: if we derived a red alert but status is 0 or -1, bump status to 2
        scanStatusInt = 2;
      }

      final aiDiagnosis = row.read<String?>('ai_diagnosis') ?? 'No recommendation';
      
      if (parsedFindings.isEmpty && aiDiagnosis != 'No recommendation' && aiDiagnosis != 'Unknown' && aiDiagnosis.isNotEmpty) {
        final conf = row.read<double?>('confidence') ?? -1.0;
        final actualConf = conf > 0 ? conf : 0.0;
        parsedFindings.add(AIFinding(
          region: aiDiagnosis,
          observation: 'Primary diagnosis',
          riskLevel: isRedAlert ? 'High' : (scanStatusInt == 1 ? 'Moderate' : (scanStatusInt == 0 ? 'Normal' : (actualConf >= 0.5 ? 'Moderate' : 'Normal'))),
          confidence: actualConf,
        ));
      }

      final modelVersion = meta['model_version'] ?? meta['aiModel'] ?? 'Cloud API Analysis';
      final inferenceSource = row.read<String?>('inference_source') ?? meta['method'] ?? 'Cloud API';

      String imagePathRaw = row.read<String?>('image_url') ?? '';
      if (imagePathRaw.isNotEmpty && 
          !imagePathRaw.startsWith('http') && 
          !imagePathRaw.startsWith('/') && 
          !imagePathRaw.startsWith('C:') && 
          !imagePathRaw.contains('/data/')) {
        // It's a cloud storage path, convert to full URL so AuthenticatedNetworkImage can parse it
        imagePathRaw = '${EnvConfig.supabaseUrl}/storage/v1/object/authenticated/scan-images/$imagePathRaw';
      }

      return DiagnosticResult(
        id: row.read<String?>('scan_id') ?? row.read<String?>('id') ?? '',
        scanDate: DateTime.tryParse(row.read<String?>('scan_date') ?? row.read<String?>('created_at') ?? '') ?? DateTime.now(),
        imagePath: imagePathRaw,
        scanType: scanTypeStr, 
        overallConfidence: row.read<double?>('confidence') ?? -1.0,
        recommendation: aiDiagnosis,
        aiModel: modelVersion,
        method: inferenceSource,
        isRedAlert: isRedAlert,
        scanStatus: scanStatusInt,
        tags: tags.isEmpty ? ['Analyzed'] : tags,
        xai: XAIInfo(
          status: xaiStatus,
          kind: xaiUrl != null ? 'heatmap_overlay' : null,
          url: xaiUrl,
        ),
        findings: parsedFindings,
      );
    }).toList();
  });
});