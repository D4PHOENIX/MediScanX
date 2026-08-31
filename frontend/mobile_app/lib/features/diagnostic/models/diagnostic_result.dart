// lib/features/diagnostic/models/diagnostic_result.dart

class AIFinding {
  final String region;
  final String observation;
  final String riskLevel; // 'High', 'Moderate', 'Normal'
  final double confidence; // e.g., 0.942

  AIFinding({
    required this.region,
    required this.observation,
    required this.riskLevel,
    required this.confidence,
  });
}

class DiagnosticResult {
  final String scanType; // e.g., 'Chest X-Ray'
  final String aiModel; // e.g., 'DenseNet-121'
  final String method; // e.g., 'Grad-CAM++'
  final double overallConfidence;
  final bool isRedAlert;
  final List<String> tags; // e.g., ['GGO', 'PE']
  final List<AIFinding> findings;
  final String recommendation;

  DiagnosticResult({
    required this.scanType,
    required this.aiModel,
    required this.method,
    required this.overallConfidence,
    required this.isRedAlert,
    required this.tags,
    required this.findings,
    required this.recommendation,
  });
}