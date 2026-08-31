// lib/features/dashboard/models/temporal_models.dart

import '../../diagnostic/models/diagnostic_result.dart'; // For XAIInfo

class PatientHistoryScan {
  final String scanId;
  final String scanType;
  final DateTime scanDate;
  final String aiDiagnosis;
  final String riskLevel;
  final int scanStatus;
  final double confidence;
  final XAIInfo? xai;

  PatientHistoryScan({
    required this.scanId,
    required this.scanType,
    required this.scanDate,
    required this.aiDiagnosis,
    required this.riskLevel,
    this.scanStatus = 0,
    required this.confidence,
    this.xai,
  });

  factory PatientHistoryScan.fromJson(Map<String, dynamic> json) {
    XAIInfo? xaiData;
    if (json['explainability'] != null && json['explainability'] is Map) {
      final explain = json['explainability'];
      xaiData = XAIInfo(
        status: explain['status']?.toString() ?? 'none',
        kind: 'heatmap_overlay',
        url: explain['url']?.toString(),
      );
    }

    return PatientHistoryScan(
      scanId: json['scan_id'] ?? '',
      scanType: json['modality'] ?? json['scan_type'] ?? 'Unknown',
      scanDate: DateTime.tryParse(json['scan_date'] ?? '') ?? DateTime.now(),
      aiDiagnosis: json['ai_diagnosis'] ?? 'Unknown',
      riskLevel: json['risk_level'] ?? 'Normal',
      scanStatus: json['scan_status'] ?? (json['risk_level'] == 'High' ? 2 : (json['risk_level'] == 'Moderate' ? 1 : 0)),
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      xai: xaiData,
    );
  }
}

class PatientHistoryResponse {
  final int totalCount;
  final List<PatientHistoryScan> items;

  PatientHistoryResponse({
    required this.totalCount,
    required this.items,
  });

  factory PatientHistoryResponse.fromJson(Map<String, dynamic> json) {
    return PatientHistoryResponse(
      totalCount: json['total_count'] ?? 0,
      items: (json['items'] as List<dynamic>?)
              ?.map((e) => PatientHistoryScan.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
    );
  }
}

class TrendAnalysis {
  final String modality;
  final String trend; // "IMPROVING" | "STABLE" | "WORSENING" | "INSUFFICIENT_DATA"
  final double delta;
  final int dataPoints;
  final String? fromDiagnosis;
  final String? toDiagnosis;

  TrendAnalysis({
    required this.modality,
    required this.trend,
    required this.delta,
    required this.dataPoints,
    this.fromDiagnosis,
    this.toDiagnosis,
  });

  factory TrendAnalysis.fromJson(Map<String, dynamic> json) {
    final scans = json['scans'] as List<dynamic>? ?? [];
    final transitions = json['transitions'] as List<dynamic>? ?? [];
    
    String parsedTrend = 'INSUFFICIENT_DATA';
    double parsedDelta = 0.0;
    String? fromDiag;
    String? toDiag;

    if (transitions.isNotEmpty) {
      final latestTransition = transitions.last as Map<String, dynamic>;
      final transitionStr = (latestTransition['direction'] as String?)?.toLowerCase() ?? '';
      fromDiag = latestTransition['from_diagnosis'] as String?;
      toDiag = latestTransition['to_diagnosis'] as String?;
      parsedDelta = (latestTransition['confidence_delta'] as num?)?.toDouble() ?? 0.1;
      
      if (transitionStr == 'worsening') {
        parsedTrend = 'WORSENING';
      } else if (transitionStr == 'improving') {
        parsedTrend = 'IMPROVING';
      } else if (transitionStr == 'unchanged') {
        parsedTrend = 'UNCHANGED';
      } else if (transitionStr == 'changed') {
        parsedTrend = 'CHANGED';
      } else if (transitionStr == 'indeterminate') {
        parsedTrend = 'INDETERMINATE';
      } else {
        parsedTrend = 'STABLE';
      }
    } else if (scans.isNotEmpty) {
        parsedTrend = 'INSUFFICIENT_DATA';
    }

    return TrendAnalysis(
      modality: 'ALL',
      trend: parsedTrend,
      delta: parsedDelta,
      dataPoints: scans.length,
      fromDiagnosis: fromDiag,
      toDiagnosis: toDiag,
    );
  }
}
