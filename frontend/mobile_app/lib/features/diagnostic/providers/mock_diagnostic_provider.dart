// lib/features/diagnostic/providers/mock_diagnostic_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/diagnostic_result.dart';

// A simple provider that returns our mock dataset
final diagnosticResultProvider = Provider<DiagnosticResult>((ref) {
  return DiagnosticResult(
    scanType: 'Chest X-Ray',
    aiModel: 'DenseNet-121',
    method: 'Grad-CAM++',
    overallConfidence: 0.942,
    isRedAlert: true,
    tags: ['GGO', 'PE'],
    recommendation: 'Evidence-based protocol: Urgent pulmonology consult recommended. Initiate supportive oxygen therapy.',
    findings: [
      AIFinding(
        region: 'Left Lower Lobe',
        observation: 'Ground-glass opacity',
        riskLevel: 'High',
        confidence: 0.942,
      ),
      AIFinding(
        region: 'Right Middle Lobe',
        observation: 'Pleural effusion',
        riskLevel: 'Moderate',
        confidence: 0.875,
      ),
      AIFinding(
        region: 'Cardiac Silhouette',
        observation: 'Normal borders',
        riskLevel: 'Normal',
        confidence: 0.981,
      ),
    ],
  );
});