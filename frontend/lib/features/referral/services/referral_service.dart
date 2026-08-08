import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../../../core/network/api_client.dart';
import '../models/referral_models.dart';

class ReferralService {
  final ApiClient _apiClient = ApiClient();

  Future<ReferralResponse?> generateReferral({
    required String patientId,
    required List<String> scanIds,
  }) async {
    try {
      debugPrint('📤 Generating Medical Report for patient: $patientId, scans: $scanIds');

      Response response = await _apiClient.dio.post(
        '/reports/generate',
        data: {
          "patient_id": patientId,
          "selected_scan_ids": scanIds,
        },
        options: Options(
          validateStatus: (status) => status != null && status < 600,
          sendTimeout: const Duration(seconds: 60),
          receiveTimeout: const Duration(seconds: 60),
        ),
      );

      debugPrint('📥 Report API response: ${response.statusCode}');

      if (response.statusCode == 200 || response.statusCode == 201) {
        debugPrint('✅ Report Generated Successfully!');
        return ReferralResponse.fromJson(response.data);
      }
      
      if (response.statusCode == 403) {
        throw Exception('One or more of the selected scans is not accessible or belongs to a different patient.');
      }

      debugPrint('🔴 Report API returned ${response.statusCode}: ${response.data}');
      return null;
    } on DioException catch (e) {
      debugPrint('🔴 Report API DioException: ${e.response?.statusCode} - ${e.message}');
      return null;
    } catch (e) {
      debugPrint('🔴 Report API Failed: $e');
      if (e is Exception && e.toString().contains('not accessible')) rethrow;
      return null;
    }
  }

  Future<CloudReportResponse?> getReports({int limit = 20, int offset = 0}) async {
    try {
      Response response = await _apiClient.dio.get(
        '/reports',
        queryParameters: {'limit': limit, 'offset': offset},
        options: Options(validateStatus: (status) => status != null && status < 600),
      );
      if (response.statusCode == 200) {
        debugPrint('📋 Raw reports response: ${response.data}');
        return CloudReportResponse.fromJson(response.data);
      }
      return null;
    } catch (e) {
      debugPrint('🔴 Failed to fetch cloud reports: $e');
      return null;
    }
  }

  Future<bool> deleteReport(String reportId) async {
    try {
      Response response = await _apiClient.dio.delete(
        '/reports/$reportId',
        options: Options(validateStatus: (status) => status != null && status < 600),
      );
      // Backend contract: 204 means success. 404 means already gone (treat as success). 500 means error.
      if ((response.statusCode != null && response.statusCode! >= 200 && response.statusCode! < 300) || response.statusCode == 404) {
        return true;
      }
      if (response.statusCode == 500) {
        throw Exception('Storage deletion failed');
      }
      return false;
    } catch (e) {
      debugPrint('🔴 Failed to delete cloud report: $e');
      rethrow;
    }
  }

  /// Download a report PDF to a local file path.
  /// Uses the freshly signed URL provided by the backend.
  Future<bool> downloadReportToFile(String reportId, String? reportUrl, String savePath) async {
    debugPrint('📋 Download strategy starting for report $reportId, reportUrl="$reportUrl"');

    if (reportUrl == null || reportUrl.isEmpty) {
      debugPrint('🔴 Report URL is null or empty, treating as download unavailable.');
      return false;
    }

    if (reportUrl.startsWith('http')) {
      return await _downloadAndValidate(reportUrl, savePath, 'Direct URL');
    }
    
    debugPrint('🔴 Report URL is not a valid HTTP URL: $reportUrl');
    return false;
  }

  /// Download a file and validate it's actually a PDF
  Future<bool> _downloadAndValidate(String url, String savePath, String label) async {
    try {
      debugPrint('📋 $label: Downloading from $url');
      await Dio().download(url, savePath);
      
      // Validate the file is actually a PDF
      final file = File(savePath);
      if (await file.exists() && await file.length() > 4) {
        final bytes = await file.openRead(0, 5).first;
        final header = String.fromCharCodes(bytes);
        if (header.startsWith('%PDF')) {
          debugPrint('✅ $label: Valid PDF downloaded (${await file.length()} bytes)');
          return true;
        } else {
          debugPrint('⚠️ $label: Downloaded file is NOT a PDF (header: $header). Deleting.');
          await file.delete();
        }
      } else {
        debugPrint('⚠️ $label: Downloaded file is empty or too small. Deleting.');
        if (await file.exists()) await file.delete();
      }
    } catch (e) {
      debugPrint('📋 $label: Download failed: $e');
      // Clean up partial download
      try { await File(savePath).delete(); } catch (_) {}
    }
    return false;
  }
}