import 'package:flutter/foundation.dart';
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
  final String patientId;
  final String? patientName;
  final String? patientUsername;
  final String reportUrl;

  TriageItem({
    required this.scanId,
    required this.modality,
    required this.aiDiagnosis,
    required this.confidence,
    required this.scanStatus,
    required this.scanDate,
    required this.patientRef,
    required this.patientId,
    this.patientName,
    this.patientUsername,
    required this.reportUrl,
  });

  factory TriageItem.fromJson(Map<String, dynamic> json) {
    debugPrint('🟡 [Triage] raw item: $json');
    return TriageItem(
      scanId: json['scan_id'] ?? '',
      modality: json['modality'] ?? 'Unknown',
      aiDiagnosis: json['ai_diagnosis'] ?? 'No Diagnosis',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      scanStatus: json['scan_status'] ?? 0,
      scanDate: json['scan_date'] != null ? DateTime.parse(json['scan_date']) : DateTime.now(),
      patientRef: json['patient_ref'] ?? 'Unknown Patient',
      patientId: json['patient_id'] ?? json['user_id'] ?? json['patient_ref'] ?? '',
      patientName: json['patient_name'],
      patientUsername: json['patient_username'],
      reportUrl: (json['explainability'] is Map) 
          ? (json['explainability']['url'] ?? '') 
          : '',
    );
  }
}

class TriageQueueNotifier extends AsyncNotifier<List<TriageItem>> {
  @override
  Future<List<TriageItem>> build() async {
    final apiService = ref.watch(triageApiServiceProvider);
    final rawData = await apiService.getTriageScans(limit: 50);

    debugPrint('🟡 [Triage] API returned ${rawData.length} raw items');

    final items = rawData.map((e) => TriageItem.fromJson(e)).toList();

    // Trust the backend — it already filters by active care relationships.
    // Sorting: worst-first, then newest-first.
    items.sort((a, b) {
      final priority = _riskRank(b.scanStatus).compareTo(_riskRank(a.scanStatus));
      if (priority != 0) return priority;
      return b.scanDate.compareTo(a.scanDate);
    });

    return items;
  }

  void removeScan(String scanId) {
    if (state.value != null) {
      state = AsyncData(state.value!.where((s) => s.scanId != scanId).toList());
    }
  }
}

final triageQueueProvider = AsyncNotifierProvider<TriageQueueNotifier, List<TriageItem>>(() {
  return TriageQueueNotifier();
});

int _riskRank(int scanStatus) {
  switch (scanStatus) {
    case 2: return 3; // High Risk
    case 1: return 2; // Moderate
    case 0: return 1; // Normal
    default: return 0; // Unknown
  }
}
