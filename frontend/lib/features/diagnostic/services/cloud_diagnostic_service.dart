import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../../../core/network/api_client.dart';

class CloudDiagnosticService {
  Future<Map<String, dynamic>?> analyzeCXR(File imageFile) async {
    return _uploadImage(imageFile, '${ApiConstants.baseUrl}/cxr/predict', 'jpeg');
  }

  Future<Map<String, dynamic>?> analyzeECG(File imageFile) async {
    return _uploadImage(imageFile, '${ApiConstants.baseUrl}/ecg/predict', 'png');
  }

  Future<Map<String, dynamic>?> analyzeSkin(File imageFile) async {
    return _uploadImage(imageFile, '${ApiConstants.baseUrl}/skin/predict', 'jpeg');
  }

  /// Returns a fresh, valid JWT — refreshing the Supabase session if needed.
  /// Returns null if the user is not authenticated or refresh fails.
  Future<String?> _getFreshToken() async {
    var session = Supabase.instance.client.auth.currentSession;
    if (session == null) return null;

    // Refresh if the token is expired or will expire within the next 60 seconds
    final expiresAt = session.expiresAt;
    final nowSecs = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    final isExpiredOrExpiringSoon = expiresAt != null && expiresAt - nowSecs < 60;

    if (isExpiredOrExpiringSoon) {
      debugPrint('🔄 [CloudDiagnosticService] JWT expiring — refreshing session...');
      try {
        final refreshed = await Supabase.instance.client.auth.refreshSession();
        session = refreshed.session;
        if (session == null) {
          debugPrint('🔴 [CloudDiagnosticService] Session refresh failed.');
          return null;
        }
        debugPrint('✅ [CloudDiagnosticService] Token refreshed successfully.');
      } catch (e) {
        debugPrint('🔴 [CloudDiagnosticService] Session refresh threw: $e');
        return null;
      }
    }

    return session.accessToken;
  }

  Future<Map<String, dynamic>?> _uploadImage(
    File imageFile,
    String url,
    String defaultExtension,
  ) async {
    try {
      final jwtToken = await _getFreshToken();
      if (jwtToken == null) {
        debugPrint('🔴 [CloudDiagnosticService] No valid token. Cannot reach cloud API.');
        return null;
      }

      var request = http.MultipartRequest('POST', Uri.parse(url));
      request.headers['Authorization'] = 'Bearer $jwtToken';
      request.headers['accept'] = 'application/json';

      // Dynamically extract the extension from the file path
      String actualExtension = imageFile.path.split('.').last.toLowerCase();
      if (actualExtension != 'jpg' && actualExtension != 'jpeg' && actualExtension != 'png') {
        actualExtension = defaultExtension; // Fallback to default if unknown
      }
      if (actualExtension == 'jpg') actualExtension = 'jpeg';

      request.files.add(
        await http.MultipartFile.fromPath(
          'file',
          imageFile.path,
          contentType: MediaType('image', actualExtension),
        ),
      );

      var streamedResponse = await request.send();
      var response = await http.Response.fromStream(streamedResponse);

      if (response.statusCode == 200) {
        debugPrint('✅ [CloudDiagnosticService] Scan successful at $url');
        final parsed = jsonDecode(response.body) as Map<String, dynamic>;
        debugPrint('🔍 [CloudDiagnosticService] Response keys: ${parsed.keys.toList()}');
        // Log finding-level keys to identify heatmap field name
        final findings = parsed['top_findings'] as List<dynamic>? ?? [];
        if (findings.isNotEmpty) {
          debugPrint('🔍 [CloudDiagnosticService] First finding keys: ${(findings.first as Map).keys.toList()}');
          // Log heatmap-related values (first 80 chars to avoid flooding)
          for (final f in findings) {
            final fMap = f as Map<String, dynamic>;
            fMap.forEach((key, value) {
              if (key.toLowerCase().contains('heat') || key.toLowerCase().contains('cam') || key.toLowerCase().contains('map')) {
                final valStr = value?.toString() ?? 'null';
                debugPrint('🔥 [CloudDiagnosticService] $key = ${valStr.length > 80 ? '${valStr.substring(0, 80)}... (${valStr.length} chars)' : valStr}');
              }
            });
          }
        } else {
          debugPrint('⚠️ [CloudDiagnosticService] top_findings is empty or missing');
        }
        return parsed;
      } else if (response.statusCode >= 400 && response.statusCode < 500) {
        debugPrint('🔴 [CloudDiagnosticService] Backend ${response.statusCode}: ${response.body}');
        try {
          final parsed = jsonDecode(response.body);
          
          // Specific handling for 422 Unprocessable Entity (like ECG validation errors)
          if (response.statusCode == 422) {
             final details = parsed['detail'] ?? parsed['details'] ?? parsed['message'] ?? 'Invalid input';
             final guidance = parsed['guidance'];
             String errorMsg = details is List ? (details.isNotEmpty ? details[0]['msg'] ?? 'Validation error' : 'Validation error') : details.toString();
             if (guidance != null && guidance.toString().isNotEmpty) {
                 throw Exception('$errorMsg\n\nGuidance: $guidance');
             }
             throw Exception(errorMsg);
          }

          final msg = parsed['message'] ?? parsed['detail'] ?? 'Analysis failed';
          final guidance = parsed['guidance'];
          if (guidance != null && guidance.toString().isNotEmpty) {
            throw Exception('$msg\n\nGuidance: $guidance');
          } else {
            throw Exception(msg);
          }
        } catch (e) {
          if (e is Exception && !e.toString().contains('FormatException')) {
            rethrow; // Rethrow our custom Exception with guidance
          }
          throw Exception('Server returned ${response.statusCode} error');
        }
      } else {
        debugPrint('🔴 [CloudDiagnosticService] Backend ${response.statusCode}: ${response.body}');
        throw Exception('Server error (${response.statusCode})');
      }
    } catch (e) {
      debugPrint('🔴 [CloudDiagnosticService] Exception: $e');
      if (e is Exception && !e.toString().contains('FormatException')) {
         rethrow; // Allow intentional validation errors to bubble up
      }
      return null;
    }
  }

  Future<http.Response?> syncEdgeInference({
    required File imageFile,
    required String scanId,
    required int scanType,
    required int scanStatus,
    required String aiDiagnosis,
    required double confidence,
    required String modality,
    required String patientId,
    String? findings,
    String? metadata,
  }) async {
    try {
      final jwtToken = await _getFreshToken();
      if (jwtToken == null) {
        debugPrint('🔴 [CloudDiagnosticService] No valid token for sync.');
        return null;
      }

      var request = http.MultipartRequest('POST', Uri.parse('${ApiConstants.baseUrl}/sync/edge-inference'));
      request.headers['Authorization'] = 'Bearer $jwtToken';
      request.headers['accept'] = 'application/json';

      request.fields['scan_id'] = scanId;
      request.fields['scan_type'] = scanType.toString();
      request.fields['scan_status'] = scanStatus.toString();
      request.fields['ai_diagnosis'] = aiDiagnosis;
      request.fields['confidence'] = confidence.toString();
      request.fields['modality'] = modality;
      request.fields['patient_id'] = patientId;
      
      if (findings != null) request.fields['findings'] = findings;
      if (metadata != null) request.fields['metadata'] = metadata;

      String actualExtension = imageFile.path.split('.').last.toLowerCase();
      if (actualExtension != 'jpg' && actualExtension != 'jpeg' && actualExtension != 'png') {
        actualExtension = 'jpeg'; // Fallback
      }
      if (actualExtension == 'jpg') actualExtension = 'jpeg';

      request.files.add(
        await http.MultipartFile.fromPath(
          'file',
          imageFile.path,
          contentType: MediaType('image', actualExtension),
        ),
      );

      var streamedResponse = await request.send();
      return await http.Response.fromStream(streamedResponse);
    } catch (e) {
      debugPrint('🔴 [CloudDiagnosticService] syncEdgeInference Exception: $e');
      return null;
    }
  }
}