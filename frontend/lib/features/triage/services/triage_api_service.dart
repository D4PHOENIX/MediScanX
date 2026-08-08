import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';
import '../../../core/network/api_client.dart';

class TriageApiService {
  Future<String?> _getFreshToken() async {
    var session = Supabase.instance.client.auth.currentSession;
    if (session == null) return null;

    final expiresAt = session.expiresAt;
    final nowSecs = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    final isExpiredOrExpiringSoon = expiresAt != null && expiresAt - nowSecs < 60;

    if (isExpiredOrExpiringSoon) {
      try {
        final refreshed = await Supabase.instance.client.auth.refreshSession();
        session = refreshed.session;
      } catch (e) {
        debugPrint('🔴 [TriageApiService] Session refresh threw: $e');
        return null;
      }
    }
    return session?.accessToken;
  }

  /// Claims a scan using a QR token. Returns the JSON response body.
  Future<Map<String, dynamic>?> claimScan(String token) async {
    try {
      final jwtToken = await _getFreshToken();
      if (jwtToken == null) return null;

      final url = Uri.parse('${ApiConstants.baseUrl}/scans/claim');
      final response = await http.post(
        url,
        headers: {
          'Authorization': 'Bearer $jwtToken',
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: jsonEncode({'token': token}),
      );

      if (response.statusCode == 200) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      } else {
        debugPrint('🔴 [TriageApiService] claimScan failed: ${response.statusCode} - ${response.body}');
        try {
          return jsonDecode(response.body) as Map<String, dynamic>;
        } catch (_) {
          return null;
        }
      }
    } catch (e) {
      debugPrint('🔴 [TriageApiService] claimScan Exception: $e');
      return null;
    }
  }

  /// Fetches the triage list for the authenticated doctor.
  Future<List<Map<String, dynamic>>> getTriageScans({int limit = 20, int offset = 0}) async {
    try {
      final jwtToken = await _getFreshToken();
      if (jwtToken == null) return [];

      final url = Uri.parse('${ApiConstants.baseUrl}/scans/triage?limit=$limit&offset=$offset');
      final response = await http.get(
        url,
        headers: {
          'Authorization': 'Bearer $jwtToken',
          'Accept': 'application/json',
        },
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final items = data['items'] as List<dynamic>? ?? [];
        return items.cast<Map<String, dynamic>>();
      } else {
        debugPrint('🔴 [TriageApiService] getTriageScans failed: ${response.statusCode}');
        return [];
      }
    } catch (e) {
      debugPrint('🔴 [TriageApiService] getTriageScans Exception: $e');
      return [];
    }
  }
}
