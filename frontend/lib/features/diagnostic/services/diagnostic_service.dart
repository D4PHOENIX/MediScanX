// lib/features/diagnostic/providers/diagnostic_service.dart
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:connectivity_plus/connectivity_plus.dart';

// Import your engines and models!
import '../../../core/ml/cxr_tflite_engine.dart';
import '../models/diagnostic_result.dart';
import 'cloud_diagnostic_service.dart';
import 'package:uuid/uuid.dart';
import '../../../core/config/env_config.dart';

// The 20 exact labels expected by your offline TFLite model
const List<String> _cxrLabels = [
  "No Finding", "Enlarged Cardiomediastinum", "Cardiomegaly", "Lung Opacity",
  "Lung Lesion", "Edema", "Consolidation", "Pneumonia", "Atelectasis",
  "Pneumothorax", "Pleural Effusion", "Pleural Other", "Fracture", "Support Devices",
  "Abnormal", "Fluid Accumulation", "Missing Lung Tissue", "Other", "Cardiac", "Opacity"
];

const _uuid = Uuid();

// 1. Keep our engines alive in Riverpod
final tfLiteEngineProvider = Provider<TFLiteEngine>((ref) {
  final engine = TFLiteEngine();
  engine.loadModel(); // Boot up the offline brain in the background
  return engine;
});

final cloudDiagnosticProvider = Provider<CloudDiagnosticService>((ref) {
  return CloudDiagnosticService(); // The Dio client we built earlier
});

// 2. THE TRAFFIC COP
final analyzeXRayProvider = FutureProvider.family<DiagnosticResult?, File>((ref, imageFile) async {

  final cloudService = ref.read(cloudDiagnosticProvider);
  final localEngine = ref.read(tfLiteEngineProvider);

  // ==========================================
  // ROUTE A: ONLINE (CLOUD API)
  // ==========================================
  final connectivityResult = await Connectivity().checkConnectivity();
  final hasInternet = !connectivityResult.contains(ConnectivityResult.none);

  if (hasInternet) {
    debugPrint('🌐 Internet detected! Routing to Cloud API...');
    try {
      final cloudData = await cloudService.analyzeCXR(imageFile);

      if (cloudData != null) {
        // Translate the FastAPI JSON into your beautiful UI Model
        List<AIFinding> mappedFindings = [];
        double highestConfidence = 0.0;
        bool isRedAlert = false;
        List<String> activeTags = [];
        String? extractedHeatmap;

        final findingsList = cloudData['top_findings'] as List<dynamic>? ?? [];

        for (var finding in findingsList) {
          final label = finding['label'] ?? 'Unknown';
          // ✅ FIX 7: Safe numerical parsing to prevent casting crashes
          final conf = (finding['confidence'] as num?)?.toDouble() ?? 0.0;
          final risk = finding['risk_level'] ?? 'Normal';

          if (conf > highestConfidence) highestConfidence = conf;
          if (risk == 'HIGH' || risk == 'CRITICAL') isRedAlert = true;
          if (activeTags.length < 2) activeTags.add(label);

          // Grab the overlay_path from finding if available (for per-finding overlay)
          if (extractedHeatmap == null) {
            extractedHeatmap = finding['overlay_path'] as String?;
          }

          mappedFindings.add(AIFinding(region: label, observation: 'Cloud API Analysis', riskLevel: risk, confidence: conf));
        }

        // xai_path and xai_status are now returned as direct fields on the row
        final xaiStatus = cloudData['xai_status'] as String? ?? 'not_requested';
        final xaiPath = cloudData['xai_path'] as String? ?? extractedHeatmap; // fallback to finding overlay_path
        
        String? xaiUrl;
        if (xaiPath != null) {
          xaiUrl = '${EnvConfig.supabaseUrl}/storage/v1/object/authenticated/scan-images/$xaiPath';
        }


        return DiagnosticResult(
          // ✅ FIX 1, 2, 3: Injected required properties for Route A
          id: cloudData['scan_id'] as String? ?? _uuid.v4(),
          scanDate: DateTime.now(),
          imagePath: cloudData['image_url'] as String? ?? imageFile.path,

          scanType: 'Chest X-Ray',
          aiModel: cloudData['model_version'] ?? 'Cloud-DenseNet-v1',
          method: 'High-Fidelity Cloud Inference',
          overallConfidence: highestConfidence,
          isRedAlert: isRedAlert,
          tags: activeTags.isEmpty ? ['Analyzed'] : activeTags,
          recommendation: isRedAlert ? 'Urgent clinical correlation required.' : 'No major anomalies detected.',
          findings: mappedFindings,
          xai: XAIInfo(
            status: xaiStatus,
            kind: xaiUrl != null ? 'heatmap_overlay' : null,
            url: xaiUrl,
            note: null,
          ),
        );
      }
    } catch (e) {
      debugPrint('⚠️ Cloud API Failed. Gracefully falling back to local model: $e');
    }
  }

  // ==========================================
  // ROUTE B: OFFLINE (LOCAL TFLITE FALLBACK)
  // ==========================================
  debugPrint('📴 Offline mode. Routing to Local TFLite Model...');
  final probabilities = await localEngine.predict(imageFile);
  if (probabilities == null) return null;

  List<AIFinding> generatedFindings = [];
  bool redAlertTriggered = false;
  double highestConfidence = 0.0;
  List<String> activeTags = [];

  for (int i = 0; i < _cxrLabels.length; i++) {
    final double confidence = probabilities[i];
    final String labelName = _cxrLabels[i];

    if (confidence > highestConfidence && labelName != "No Finding") {
      highestConfidence = confidence;
    }

    if (confidence > 0.50) {
      String risk = confidence > 0.75 ? 'High' : 'Moderate';
      if (risk == 'High' && labelName != "No Finding" && labelName != "Support Devices") {
        redAlertTriggered = true;
      }
      generatedFindings.add(AIFinding(region: labelName, observation: 'Offline Edge AI', riskLevel: risk, confidence: confidence));
      if (activeTags.length < 2 && labelName != "Abnormal") activeTags.add(labelName);
    }
  }

  generatedFindings.sort((a, b) => b.confidence.compareTo(a.confidence));

  int edgeScanStatus = redAlertTriggered ? 2 : (highestConfidence > 0.50 ? 1 : 0);

  return DiagnosticResult(
    // ✅ FIX 4, 5, 6: Injected required properties for Route B
    id: _uuid.v4(),
    scanDate: DateTime.now(),
    imagePath: imageFile.path,

    scanType: 'Chest X-Ray',
    aiModel: 'DenseNet-121 (Offline)',
    method: 'Quantized Edge TFLite',
    overallConfidence: highestConfidence,
    isRedAlert: redAlertTriggered,
    scanStatus: edgeScanStatus,
    tags: activeTags.isEmpty ? ['Normal'] : activeTags,
    recommendation: redAlertTriggered ? 'High confidence anomaly detected offline.' : 'No major anomalies detected.',
    findings: generatedFindings.isEmpty
        ? [AIFinding(region: 'All regions', observation: 'No anomalies', riskLevel: 'Normal', confidence: (probabilities[0] as num).toDouble())]
        : generatedFindings,
    xai: XAIInfo(status: 'skipped_edge'),
  );
});