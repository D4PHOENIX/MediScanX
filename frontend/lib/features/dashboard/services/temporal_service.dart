// lib/features/dashboard/services/temporal_service.dart
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import '../../../core/network/api_client.dart';
import '../models/temporal_models.dart';

class TemporalService {
  final ApiClient _apiClient = ApiClient();

  Future<PatientHistoryResponse?> getPatientHistory({String? modality}) async {
    try {
      final queryParams = modality != null ? {'modality': modality} : null;
      final response = await _apiClient.dio.get(
        '/scans/history',
        queryParameters: queryParams,
      );
      if (response.statusCode == 200) {
        return PatientHistoryResponse.fromJson(response.data);
      }
      return null;
    } catch (e) {
      debugPrint('🔴 Patient History API Failed: $e');
      return null;
    }
  }

  Future<TrendAnalysis?> getPatientTrends(String modality) async {
    try {
      final queryParams = {'modality': modality};
      final response = await _apiClient.dio.get(
        '/scans/trends',
        queryParameters: queryParams,
      );
      if (response.statusCode == 200) {
        return TrendAnalysis.fromJson(response.data);
      }
      return null;
    } catch (e) {
      debugPrint('🔴 Patient Trends API Failed: $e');
      return null;
    }
  }
}
