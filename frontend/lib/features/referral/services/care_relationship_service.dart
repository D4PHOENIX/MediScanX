import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:http/http.dart' as http;
import '../../../core/network/api_client.dart';

class CareRelationshipService {
  final SupabaseClient supabase = Supabase.instance.client;

  String? get _token => Supabase.instance.client.auth.currentSession?.accessToken;

  /// Doctor asks for access. Returns the new relationship id (UUID string).
  Future<String?> requestCare({required String patientUserId, String? note}) async {
    try {
      final response = await supabase.rpc('request_care', params: {
        'p_patient': patientUserId,
        if (note != null) 'p_note': note,
      });
      return response?.toString();
    } catch (e) {
      debugPrint('Error requesting care: $e');
      rethrow;
    }
  }

  /// Patient accepts or declines. relationshipId is a UUID string.
  Future<void> respondToCare({required String relationshipId, required bool accept}) async {
    try {
      await supabase.rpc('respond_to_care', params: {
        'p_id': relationshipId,
        'p_accept': accept,
      });
    } catch (e) {
      debugPrint('Error responding to care: $e');
      rethrow;
    }
  }

  /// Patient revokes a doctor's access via the gateway API.
  /// Returns the HTTP status code: 200 = revoked, 404 = already ended, 422 = bad ID.
  Future<int> revokeCare({required String relationshipId}) async {
    try {
      final token = _token;
      if (token == null) throw Exception('Not authenticated');

      final response = await http.post(
        Uri.parse('${ApiConstants.baseUrl}/patients/care-relationships/revoke'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: jsonEncode({'relationship_id': relationshipId}),
      );

      debugPrint('[CareRelationshipService] revoke status: ${response.statusCode}');
      return response.statusCode;
    } catch (e) {
      debugPrint('Error revoking care: $e');
      rethrow;
    }
  }
}
