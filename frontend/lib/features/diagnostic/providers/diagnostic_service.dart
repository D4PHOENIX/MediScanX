// lib/features/diagnostic/providers/diagnostic_service.dart
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:mediscanx_mobile/features/diagnostic/services/cloud_diagnostic_service.dart';

// --- ML ENGINES (Strict relative paths) ---
import '../../../core/ml/cxr_tflite_engine.dart';
import '../../../core/ml/skin_tflite_engine.dart';

// --- MODELS & SERVICES ---
import '../models/diagnostic_result.dart';
import 'package:uuid/uuid.dart';
// ==========================================
// CHEST X-RAY CONSTANTS & PROVIDERS
// ==========================================

const List<String> _cxrLabels = [
  "No Finding", "Enlarged Cardiomediastinum", "Cardiomegaly", "Lung Opacity",
  "Lung Lesion", "Edema", "Consolidation", "Pneumonia", "Atelectasis",
  "Pneumothorax", "Pleural Effusion", "Pleural Other", "Fracture", "Support Devices",
  "Abnormal", "Fluid Accumulation", "Missing Lung Tissue", "Other", "Cardiac", "Opacity"
];

final tfLiteEngineProvider = Provider<TFLiteEngine>((ref) {
  final engine = TFLiteEngine();
  engine.loadModel();
  return engine;
});

final cloudDiagnosticProvider = Provider<CloudDiagnosticService>((ref) {
  return CloudDiagnosticService();
});

// 🔴 THE FIX: Changed to a standard Provider that returns a Function
final analyzeXRayProvider = Provider((ref) {

  return (File imageFile) async {
    final cloudService = ref.read(cloudDiagnosticProvider);
    final localEngine = ref.read(tfLiteEngineProvider);

    // ROUTE A: ONLINE (CLOUD API)
    final connectivityResult = await Connectivity().checkConnectivity();
    final hasInternet = !connectivityResult.contains(ConnectivityResult.none);

    if (hasInternet) {
      debugPrint('🌐 Internet detected! Routing to Cloud API...');
      try {
        final cloudData = await cloudService.analyzeCXR(imageFile);

        if (cloudData != null) {
          List<AIFinding> mappedFindings = [];
          double highestConfidence = 0.0;
          bool isRedAlert = false;
          List<String> activeTags = [];
          String? extractedHeatmap;

          final findingsList = cloudData['top_findings'] as List<dynamic>? ?? [];

          int overallScanStatus = -1;

          for (var finding in findingsList) {
            final label = finding['label'] ?? 'Unknown';
            final conf = (finding['confidence'] as num?)?.toDouble() ?? 0.0;
            
            final statusVal = finding['scan_status'];
            int? scanStatusInt;
            if (statusVal is int) scanStatusInt = statusVal;
            else if (statusVal is String) scanStatusInt = int.tryParse(statusVal);
            
            String risk = 'Moderate'; // Default if unrecognized
            if (scanStatusInt != null) {
              if (scanStatusInt == 2) risk = 'High';
              else if (scanStatusInt == 1) risk = 'Moderate';
              else if (scanStatusInt == 0) risk = 'Normal';
            } else {
              final rawRisk = finding['risk_level']?.toString().toUpperCase();
              if (rawRisk != null) {
                if (rawRisk == 'HIGH' || rawRisk == 'CRITICAL') risk = 'High';
                else if (rawRisk == 'MODERATE' || rawRisk == 'WARNING') risk = 'Moderate';
                else risk = 'Normal';
              } else {
                if (label.toLowerCase().contains('no finding') || label.toLowerCase() == 'normal' || label.toLowerCase() == 'norm') {
                  risk = 'Normal';
                }
              }
            }

            if (risk == 'High') {
              isRedAlert = true;
              if (overallScanStatus < 2) overallScanStatus = 2;
            } else if (risk == 'Moderate') {
              if (overallScanStatus < 1) overallScanStatus = 1;
            }

            if (conf > highestConfidence) highestConfidence = conf;
            if (activeTags.length < 2) activeTags.add(label);

            mappedFindings.add(AIFinding(region: label, observation: 'Cloud API Analysis', riskLevel: risk, confidence: conf));
          }

          // Fallback to top-level fields if the backend provides them directly instead of inside top_findings
          if (cloudData.containsKey('confidence') && cloudData['confidence'] != null) {
            highestConfidence = (cloudData['confidence'] as num).toDouble();
          }
          if (cloudData.containsKey('scan_status') && cloudData['scan_status'] != null) {
            final statusRaw = cloudData['scan_status'];
            if (statusRaw is int) overallScanStatus = statusRaw;
            else if (statusRaw is String) overallScanStatus = int.tryParse(statusRaw) ?? -1;
            isRedAlert = overallScanStatus == 2;
          }
          if (cloudData.containsKey('primary_diagnosis') && cloudData['primary_diagnosis'] != null) {
            final topDiagnosis = cloudData['primary_diagnosis'];
            if (activeTags.isEmpty && topDiagnosis != null) activeTags.add(topDiagnosis.toString());
          } else if (cloudData.containsKey('ai_diagnosis') && cloudData['ai_diagnosis'] != null) {
            final topDiagnosis = cloudData['ai_diagnosis'];
            if (activeTags.isEmpty && topDiagnosis != null) activeTags.add(topDiagnosis.toString());
          }

          final explain = cloudData['explainability'];
          XAIInfo? xaiData;
          if (explain is Map) {
            xaiData = XAIInfo(
              status: explain['status']?.toString() ?? 'none',
              kind: 'heatmap_overlay',
              url: explain['url']?.toString(),
            );
          } else {
            xaiData = XAIInfo(status: 'none');
          }

            return DiagnosticResult(
              id: cloudData['scan_id'] ?? const Uuid().v4(),
              scanDate: DateTime.now(),
              imagePath: imageFile.path,
              scanType: 'Chest X-Ray',
              aiModel: cloudData['model_version'] ?? 'Cloud-DenseNet-v1',
              method: 'High-Fidelity Cloud Inference',
              overallConfidence: highestConfidence,
              isRedAlert: isRedAlert,
              scanStatus: overallScanStatus,
              tags: activeTags.isEmpty ? ['Analyzed'] : activeTags,
              recommendation: isRedAlert ? 'Urgent clinical correlation required.' : (overallScanStatus == 1 ? 'Anomalies detected. Clinical review recommended.' : (overallScanStatus == 0 ? 'No major anomalies detected.' : 'Diagnosis pending review.')),
              findings: mappedFindings,
              xai: xaiData,
            );
        }
      } catch (e) {
        if (e.toString().contains('503') || e.toString().contains('Server error')) {
          debugPrint('🔴 [CloudDiagnosticService] Backend 503: $e');
          rethrow; // Don't fall back silently on server failure, bubble it up to the UI
        }
        debugPrint('⚠️ Cloud API Failed. Gracefully falling back to local model: $e');
      }
    }

    // ROUTE B: OFFLINE (LOCAL TFLITE FALLBACK)
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

    int scanStatus = redAlertTriggered ? 2 : (generatedFindings.isNotEmpty && highestConfidence > 0.5 ? 1 : 0);

    return DiagnosticResult(
      id: const Uuid().v4(),
      scanDate: DateTime.now(),
      imagePath: imageFile.path,
      scanType: 'Chest X-Ray',
      aiModel: 'DenseNet-121 (Offline)',
      method: 'Quantized Edge TFLite',
      overallConfidence: highestConfidence,
      isRedAlert: redAlertTriggered,
      scanStatus: scanStatus,
      tags: activeTags.isEmpty ? ['Normal'] : activeTags,
      recommendation: redAlertTriggered ? 'High confidence anomaly detected offline.' : 'No major anomalies detected.',
      findings: generatedFindings.isEmpty
          ? [AIFinding(region: 'All regions', observation: 'No anomalies', riskLevel: 'Normal', confidence: (probabilities[0] as num).toDouble())]
          : generatedFindings,
      xai: XAIInfo(status: 'skipped_edge'),
    );
  };
});

// ==========================================
// ECG PROVIDER
// ==========================================
final analyzeECGProvider = Provider((ref) {
  return (File imageFile) async {
    final cloudService = ref.read(cloudDiagnosticProvider);

    final connectivityResult = await Connectivity().checkConnectivity();
    final hasInternet = !connectivityResult.contains(ConnectivityResult.none);

    if (hasInternet) {
      debugPrint('🌐 Internet detected! Routing ECG scan to Cloud API...');
      try {
        final cloudData = await cloudService.analyzeECG(imageFile);

        if (cloudData != null) {
          List<AIFinding> mappedFindings = [];
          double highestConfidence = 0.0;
          bool isRedAlert = false;
          List<String> activeTags = [];
          String topDiagnosis = 'Unknown';
          String? extractedHeatmap;
          String? dominantLeadsStr;

          int overallScanStatus = -1;

          final predictionsRaw = cloudData['predictions'];
          if (predictionsRaw is Map) {
            predictionsRaw.forEach((key, value) {
              if (value is Map) {
                final isDetected = value['detected'] == true;
                final prob = (value['probability'] as num?)?.toDouble() ?? 0.0;
                
                final statusVal = value['scan_status'];
                int? scanStatusInt;
                if (statusVal is int) scanStatusInt = statusVal;
                else if (statusVal is String) scanStatusInt = int.tryParse(statusVal);
                
                String risk = 'Moderate'; // Default if unrecognized
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
                  } else {
                    if (key.toUpperCase() == 'NORM' || !isDetected) {
                      risk = 'Normal';
                    }
                  }
                }

                if (prob > highestConfidence) {
                  highestConfidence = prob;
                  topDiagnosis = key;
                }

                if (isDetected) {
                  if (risk == 'High') {
                    isRedAlert = true;
                  } 
                  
                  if (activeTags.length < 2 && key != 'NORM') activeTags.add(key);
                  
                  mappedFindings.add(AIFinding(region: key, observation: 'Cloud API Analysis', riskLevel: risk, confidence: prob));
                }
              }
            });
          }

          // Fallback to top-level fields if the backend provides them directly instead of inside predictions
          if (cloudData.containsKey('confidence') && cloudData['confidence'] != null) {
            highestConfidence = (cloudData['confidence'] as num).toDouble();
          }
          if (cloudData.containsKey('scan_status') && cloudData['scan_status'] != null) {
            final statusRaw = cloudData['scan_status'];
            if (statusRaw is int) overallScanStatus = statusRaw;
            else if (statusRaw is String) overallScanStatus = int.tryParse(statusRaw) ?? -1;
            isRedAlert = overallScanStatus == 2;
          }
          if (cloudData.containsKey('primary_diagnosis') && cloudData['primary_diagnosis'] != null) {
            topDiagnosis = cloudData['primary_diagnosis'];
            if (activeTags.isEmpty) activeTags.add(topDiagnosis);
          } else if (cloudData.containsKey('ai_diagnosis') && cloudData['ai_diagnosis'] != null) {
            topDiagnosis = cloudData['ai_diagnosis'];
            if (activeTags.isEmpty) activeTags.add(topDiagnosis);
          } else if (cloudData.containsKey('predicted_class') && cloudData['predicted_class'] != null) {
            topDiagnosis = cloudData['predicted_class'];
            if (activeTags.isEmpty) activeTags.add(topDiagnosis);
          }

          if (mappedFindings.isEmpty && topDiagnosis != 'Unknown') {
            if (overallScanStatus == -1) {
               overallScanStatus = (topDiagnosis == 'NORM' || topDiagnosis.toLowerCase() == 'normal') ? 0 : 1;
            }
            mappedFindings.add(AIFinding(
              region: topDiagnosis,
              observation: 'Primary diagnosis',
              riskLevel: overallScanStatus == 2 ? 'High' : (overallScanStatus == 1 ? 'Moderate' : (overallScanStatus == 0 ? 'Normal' : 'Unknown')),
              confidence: highestConfidence,
            ));
          }

          final explain = cloudData['explainability'];
          XAIInfo? xaiData;
          if (explain is Map) {
            xaiData = XAIInfo(
              status: explain['status']?.toString() ?? 'none',
              kind: 'integrated_gradients',
              url: explain['url']?.toString(),
            );
          } else {
            xaiData = XAIInfo(status: 'none');
          }

            return DiagnosticResult(
              id: cloudData['scan_id'] ?? const Uuid().v4(),
              scanDate: DateTime.now(),
              imagePath: imageFile.path,
              scanType: 'ECG',
              aiModel: cloudData['model_version'] ?? 'Cloud-ECG-v1',
              method: 'High-Fidelity Cloud Inference',
              overallConfidence: highestConfidence,
              isRedAlert: isRedAlert,
              scanStatus: overallScanStatus,
              tags: activeTags,
              recommendation: isRedAlert 
                ? 'Urgent clinical correlation required. High risk of cardiac anomaly detected ($topDiagnosis).'
                : (overallScanStatus == 1 ? 'Anomalies detected. Clinical review recommended.' : (overallScanStatus == 0 ? 'No major anomalies detected. Routine clinical monitoring advised.' : 'Diagnosis pending review.')),
              findings: mappedFindings,
              xai: xaiData,
            );
        }
        } catch (e) {
          debugPrint('🔴 Cloud API Failed for ECG: $e');
          if (e.toString().contains('Cloud API failed')) {
             rethrow;
          }
          if (e is Exception) {
             rethrow;
          }
          throw Exception('Cloud API failed: $e');
        }
    } else {
      debugPrint('📴 Offline mode. ECG requires internet connectivity.');
      throw Exception('ECG analysis requires an active internet connection.');
    }

    // Throw error if cloud API fails to return data
    throw Exception('Failed to get a response from the ECG Cloud API.');
  };
});

// ==========================================
// SKIN LESION PROVIDER
// ==========================================
// 🔴 THE FIX: Changed to a standard Provider that returns a Function
final analyzeSkinProvider = Provider((ref) {

  return (File imageFile) async {
    final cloudService = ref.read(cloudDiagnosticProvider);
    final localEngine = SkinTfliteEngine.instance;

    // ROUTE A: ONLINE (CLOUD API)
    final connectivityResult = await Connectivity().checkConnectivity();
    final hasInternet = !connectivityResult.contains(ConnectivityResult.none);

    if (hasInternet) {
      debugPrint('🌐 Internet detected! Routing Skin scan to Cloud API...');
      try {
        final cloudData = await cloudService.analyzeSkin(imageFile);

        if (cloudData != null) {
          List<AIFinding> mappedFindings = [];
          double highestConfidence = 0.0;
          bool isRedAlert = false;
          List<String> activeTags = [];
          String? extractedHeatmap;
          String topDiagnosis = 'Unknown';

          final findingsList = (cloudData['predictions'] ?? cloudData['top_findings']) as List<dynamic>? ?? [];
          topDiagnosis = cloudData['primary_diagnosis'] ?? 'Unknown';
          int overallScanStatus = -1;

          for (var finding in findingsList) {
            final label = finding['label'] ?? 'Unknown';
            final conf = (finding['confidence'] as num?)?.toDouble() ?? 0.0;
            
            final apiRisk = cloudData['risk_assessment'];
            final statusVal = finding['scan_status'];
            int? scanStatusInt;
            if (statusVal is int) scanStatusInt = statusVal;
            else if (statusVal is String) scanStatusInt = int.tryParse(statusVal);
            
            String risk = 'Moderate'; // Default if unrecognized
            if (scanStatusInt != null) {
              if (scanStatusInt == 2) risk = 'High';
              else if (scanStatusInt == 1) risk = 'Moderate';
              else if (scanStatusInt == 0) risk = 'Normal';
            } else {
              final rawRisk = finding['risk_level']?.toString().toUpperCase();
              if (rawRisk != null) {
                if (rawRisk == 'HIGH' || rawRisk == 'CRITICAL') risk = 'High';
                else if (rawRisk == 'MODERATE' || rawRisk == 'WARNING') risk = 'Moderate';
                else risk = 'Normal';
              } else if (apiRisk != null) {
                if (apiRisk == 'MALIGNANT_RISK') risk = 'High';
                else if (apiRisk == 'BENIGN_LIKELY') risk = 'Normal';
                else risk = 'Moderate';
              } else {
                if (label.toLowerCase().contains('benign') || label.toLowerCase() == 'normal') {
                  risk = 'Normal';
                }
              }
            }

            if (risk == 'High') {
              isRedAlert = true;
              if (overallScanStatus < 2) overallScanStatus = 2;
            } else if (risk == 'Moderate') {
              if (overallScanStatus < 1) overallScanStatus = 1;
            }

            if (conf > highestConfidence) {
              highestConfidence = conf;
              if (topDiagnosis == 'Unknown') topDiagnosis = label;
            }
            if (activeTags.length < 2) activeTags.add(label);

            mappedFindings.add(AIFinding(region: label, observation: 'Cloud API Analysis', riskLevel: risk, confidence: conf));
          }

          // Fallback to top-level fields if the backend provides them directly instead of inside predictions
          if (cloudData.containsKey('confidence') && cloudData['confidence'] != null) {
            highestConfidence = (cloudData['confidence'] as num).toDouble();
          }
          if (cloudData.containsKey('scan_status') && cloudData['scan_status'] != null) {
            final statusRaw = cloudData['scan_status'];
            if (statusRaw is int) overallScanStatus = statusRaw;
            else if (statusRaw is String) overallScanStatus = int.tryParse(statusRaw) ?? -1;
            isRedAlert = overallScanStatus == 2;
          }
          if (cloudData.containsKey('primary_diagnosis') && cloudData['primary_diagnosis'] != null) {
            topDiagnosis = cloudData['primary_diagnosis'];
            if (activeTags.isEmpty) activeTags.add(topDiagnosis);
          } else if (cloudData.containsKey('ai_diagnosis') && cloudData['ai_diagnosis'] != null) {
            topDiagnosis = cloudData['ai_diagnosis'];
            if (activeTags.isEmpty) activeTags.add(topDiagnosis);
          }

          final explain = cloudData['explainability'];
          XAIInfo? xaiData;
          if (explain is Map) {
            xaiData = XAIInfo(
              status: explain['status']?.toString() ?? 'none',
              kind: 'heatmap_overlay',
              url: explain['url']?.toString(),
            );
          } else {
            xaiData = XAIInfo(status: 'none');
          }

            return DiagnosticResult(
              id: cloudData['scan_id'] ?? const Uuid().v4(),
              scanDate: DateTime.now(),
              imagePath: imageFile.path,
              scanType: 'Skin Lesion',
              aiModel: cloudData['model_version'] ?? 'Cloud-Skin-v1',
              method: 'High-Fidelity Cloud Inference',
              overallConfidence: highestConfidence,
              isRedAlert: isRedAlert,
              scanStatus: overallScanStatus,
              tags: activeTags.isEmpty ? ['Analyzed'] : activeTags,
              recommendation: isRedAlert 
                ? 'Urgent clinical correlation required. High risk of malignancy detected ($topDiagnosis).'
                : (overallScanStatus == 1 ? 'Anomalies detected. Clinical review recommended.' : 'No major anomalies detected. Routine clinical monitoring advised.'),
              findings: mappedFindings,
              xai: xaiData,
            );
        }
      } catch (e) {
        if (e.toString().contains('503') || e.toString().contains('Server error')) {
          debugPrint('🔴 [CloudDiagnosticService] Backend 503 for Skin: $e');
          rethrow; // Don't fall back silently on server failure, bubble it up to the UI
        }
        debugPrint('⚠️ Cloud API Failed for Skin. Gracefully falling back to local model: $e');
      }
    }

    // ROUTE B: OFFLINE (LOCAL TFLITE FALLBACK)
    debugPrint('📴 Offline mode. Routing Skin scan to Local TFLite Model...');
    try {
      final bytes = await imageFile.readAsBytes();

      // Call the Singleton Engine we built
      final resultsMap = await localEngine.inferSkinImage(bytes);

      if (resultsMap == null || resultsMap.isEmpty) return null;

      List<AIFinding> generatedFindings = [];
      bool redAlertTriggered = false;
      double highestConfidence = 0.0;
      String topDiagnosis = 'Unknown';
      List<String> activeTags = [];

      resultsMap.forEach((diseaseName, confidence) {
        if (confidence > highestConfidence) {
          highestConfidence = confidence;
          topDiagnosis = diseaseName;
        }

        if (confidence > 0.10) {
          String risk = 'Low';

          if (confidence > 0.65) {
            risk = 'High';
            if (diseaseName == 'Melanoma' || diseaseName == 'Basal Cell Carcinoma') {
              redAlertTriggered = true;
            }
          } else if (confidence > 0.35) {
            risk = 'Moderate';
          }

          generatedFindings.add(
            AIFinding(
              region: diseaseName,
              observation: 'Dermoscopic AI Match',
              riskLevel: risk,
              confidence: confidence,
            ),
          );

          if (activeTags.length < 2 && confidence > 0.35) {
            activeTags.add(diseaseName);
          }
        }
      });

      generatedFindings.sort((a, b) => b.confidence.compareTo(a.confidence));

      if (activeTags.isEmpty) {
        activeTags.add(topDiagnosis);
      }

      int scanStatus = redAlertTriggered ? 2 : (highestConfidence > 0.6 && topDiagnosis != 'Benign' ? 1 : 0);

      return DiagnosticResult(
        id: const Uuid().v4(),
        scanDate: DateTime.now(),
        imagePath: imageFile.path,
        scanType: 'Skin Lesion',
        aiModel: 'CNN Vision Model',
        method: 'INT8 Quantized TFLite',
        overallConfidence: highestConfidence,
        isRedAlert: redAlertTriggered,
        scanStatus: scanStatus,
        tags: activeTags,
        recommendation: redAlertTriggered
            ? 'High risk of malignancy detected ($topDiagnosis). Urgent dermatological biopsy recommended.'
            : 'Predominantly benign features identified. Routine clinical monitoring advised.',
        findings: generatedFindings.isEmpty
            ? [AIFinding(region: topDiagnosis, observation: 'Highest probability match', riskLevel: 'Low', confidence: highestConfidence)]
            : generatedFindings,
        xai: XAIInfo(status: 'skipped_edge'),
      );

    } catch (e) {
      debugPrint('Skin Analysis Error: $e');
      return null;
    }
  };
});