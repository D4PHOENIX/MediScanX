import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:flutter/foundation.dart';

class CareRelationshipService {
  final SupabaseClient supabase = Supabase.instance.client;

  /// Doctor asks for access. Returns the new relationship id.
  Future<int?> requestCare({required String patientUserId, String? note}) async {
    try {
      final response = await supabase.rpc('request_care', params: {
        'p_patient': patientUserId,
        if (note != null) 'p_note': note,
      });
      return response as int?;
    } catch (e) {
      debugPrint('Error requesting care: $e');
      rethrow;
    }
  }

  /// Patient accepts or declines.
  Future<void> respondToCare({required int relationshipId, required bool accept}) async {
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

  /// Either party ends the relationship.
  Future<void> revokeCare({required int relationshipId}) async {
    try {
      await supabase.rpc('revoke_care', params: {
        'p_id': relationshipId,
      });
    } catch (e) {
      debugPrint('Error revoking care: $e');
      rethrow;
    }
  }
}
