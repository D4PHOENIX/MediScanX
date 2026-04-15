import 'package:freezed_annotation/freezed_annotation.dart';
part 'scan_model.freezed.dart';
part 'scan_model.g.dart';

@freezed
class ScanResult with _$ScanResult{
  const factory ScanResult({
    required String id,
    required String label,
    required double confidence,
    required DateTime timestamp,
    String? remarks,
    @Default(false) bool isSynced,
}) = _ScanResult;

  factory ScanResult.fromJson(Map<String, dynamic> json) => _ScanResult.fromJson(json);
}