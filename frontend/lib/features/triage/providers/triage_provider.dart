import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/triage_api_service.dart';

final triageApiServiceProvider = Provider((ref) => TriageApiService());

class TriageItem {
  final String scanId;
  final String modality;
  final String aiDiagnosis;
  final double confidence;
  final int scanStatus;
  final DateTime scanDate;
  final String patientRef;
  final String reportUrl;

  TriageItem({
    required this.scanId,
    required this.modality,
    required this.aiDiagnosis,
    required this.confidence,
    required this.scanStatus,
    required this.scanDate,
    required this.patientRef,
    required this.reportUrl,
  });

  factory TriageItem.fromJson(Map<String, dynamic> json) {
    return TriageItem(
      scanId: json['scan_id'] ?? '',
      modality: json['modality'] ?? 'Unknown',
      aiDiagnosis: json['ai_diagnosis'] ?? 'No Diagnosis',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      scanStatus: json['scan_status'] ?? 0,
      scanDate: json['scan_date'] != null ? DateTime.parse(json['scan_date']) : DateTime.now(),
      patientRef: json['patient_ref'] ?? 'Unknown Patient',
      reportUrl: (json['explainability'] is Map) 
          ? (json['explainability']['url'] ?? '') 
          : '',
    );
  }
}

final triageQueueProvider = FutureProvider<List<TriageItem>>((ref) async {
  final apiService = ref.watch(triageApiServiceProvider);
  final rawData = await apiService.getTriageScans(limit: 50);
  
  final items = rawData.map((e) => TriageItem.fromJson(e)).toList();

  // Sorting is primarily handled by backend (worst-first), but we can guarantee client-side sorting just in case
  items.sort((a, b) {
    final priority = _riskRank(b.scanStatus).compareTo(_riskRank(a.scanStatus));
    if (priority != 0) return priority;
    return b.scanDate.compareTo(a.scanDate);
  });

  return items;
});

int _riskRank(int scanStatus) {
  switch (scanStatus) {
    case 2: return 3; // High Risk
    case 1: return 2; // Moderate
    case 0: return 1; // Normal
    default: return 0; // Unknown
  }
}
