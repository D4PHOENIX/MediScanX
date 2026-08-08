import 'package:freezed_annotation/freezed_annotation.dart';

part 'fusion_models.freezed.dart';
part 'fusion_models.g.dart';

@freezed
class FusionRequest with _$FusionRequest {
  const factory FusionRequest({
    @JsonKey(name: 'selected_scan_ids') List<String>? selectedScanIds,
  }) = _FusionRequest;

  factory FusionRequest.fromJson(Map<String, dynamic> json) =>
      _$FusionRequestFromJson(json);
}

@freezed
class ModalityRisk with _$ModalityRisk {
  const factory ModalityRisk({
    required String modality,
    @JsonKey(name: 'ai_diagnosis') required String aiDiagnosis,
    required double confidence,
    required String status,
  }) = _ModalityRisk;

  factory ModalityRisk.fromJson(Map<String, dynamic> json) =>
      _$ModalityRiskFromJson(json);
}

@freezed
class FusionResponse with _$FusionResponse {
  const factory FusionResponse({
    @JsonKey(name: 'overall_risk_score') double? overallRiskScore,
    @JsonKey(name: 'risk_level') String? riskLevel,
    @JsonKey(name: 'critical_alert') @Default(false) bool criticalAlert,
    @JsonKey(name: 'fusion_performed') @Default(false) bool fusionPerformed,
    @Default([]) List<String> unscored,
    @JsonKey(name: 'modality_risks') @Default([]) List<ModalityRisk> modalityRisks,
    @JsonKey(name: 'findings_summary') String? findingsSummary,
    @JsonKey(name: 'clinical_correlation') String? clinicalCorrelation,
  }) = _FusionResponse;

  factory FusionResponse.fromJson(Map<String, dynamic> json) =>
      _$FusionResponseFromJson(json);
}