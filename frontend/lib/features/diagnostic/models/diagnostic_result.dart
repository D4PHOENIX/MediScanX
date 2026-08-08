// lib/features/diagnostic/models/diagnostic_result.dart
import 'dart:convert';

class AIFinding {
  final String region;
  final String observation;
  final String riskLevel; // 'High', 'Moderate', 'Normal'
  final double confidence;

  AIFinding({
    required this.region,
    required this.observation,
    required this.riskLevel,
    required this.confidence,
  });

  // Convert to JSON map for database storage
  Map<String, dynamic> toJson() => {
    'region': region,
    'observation': observation,
    'riskLevel': riskLevel,
    'confidence': confidence,
  };

  // Convert from JSON map back to object
  factory AIFinding.fromJson(Map<String, dynamic> json) {
    return AIFinding(
      region: json['region'] ?? 'Unknown',
      observation: json['observation'] ?? '',
      riskLevel: json['riskLevel'] ?? 'Normal',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class DiagnosticResult {
  // --- Core Database Fields ---
  final String id;
  final DateTime scanDate;
  final String imagePath; // Path to the local device image

  // --- Rich UI Fields ---
  final String scanType;
  final String aiModel;
  final String method;
  final double overallConfidence;
  final bool isRedAlert;
  final int scanStatus; // -1: Unknown, 0: Normal, 1: Warning, 2: High Risk
  final List<String> tags;
  final List<AIFinding> findings;
  final String recommendation;
  final XAIInfo? xai;

  DiagnosticResult({
    required this.id,
    required this.scanDate,
    required this.imagePath,
    required this.scanType,
    required this.aiModel,
    required this.method,
    this.overallConfidence = -1.0,
    required this.isRedAlert,
    this.scanStatus = -1,
    required this.tags,
    required this.findings,
    required this.recommendation,
    this.xai,
  });
}

class XAIInfo {
  final String status; // 'generated', 'skipped_edge', 'failed', 'not_requested'
  final String? kind;  // 'heatmap_overlay', 'reconstructed_trace'
  final String? url;
  final String? note;

  XAIInfo({
    required this.status,
    this.kind,
    this.url,
    this.note,
  });

  Map<String, dynamic> toJson() => {
    'status': status,
    'kind': kind,
    'url': url,
    'note': note,
  };

  factory XAIInfo.fromJson(Map<String, dynamic> json) {
    return XAIInfo(
      status: json['status'] ?? 'not_requested',
      kind: json['kind'],
      url: json['url'],
      note: json['note'],
    );
  }
}