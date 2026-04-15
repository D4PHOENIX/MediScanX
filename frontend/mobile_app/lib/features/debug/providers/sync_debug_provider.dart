import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:drift/drift.dart' as drift;
import 'package:powersync/powersync.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../../core/database/database_manager.dart';
import '../../auth/providers/database_provider.dart';

class ProfileSyncDebugSnapshot {
  final DateTime capturedAt;
  final String? userId;
  final String? email;
  final Map<String, dynamic> metadata;
  final String normalizedRole;
  final String expectedTable;
  final bool foundInExpectedTable;
  final bool foundInOtherTable;
  final String? fullName;
  final String? username;
  final String? syncStatus;
  final String diagnosis;

  const ProfileSyncDebugSnapshot({
    required this.capturedAt,
    required this.userId,
    required this.email,
    required this.metadata,
    required this.normalizedRole,
    required this.expectedTable,
    required this.foundInExpectedTable,
    required this.foundInOtherTable,
    required this.fullName,
    required this.username,
    required this.syncStatus,
    required this.diagnosis,
  });
}

String _normalizeRole(Map<String, dynamic> metadata) {
  final rawRole = (metadata['role'] ?? metadata['userType'])?.toString().toLowerCase();
  return rawRole == 'doctor' ? 'Doctor' : 'Patient';
}

Future<ProfileSyncDebugSnapshot> _buildProfileSnapshot(Ref ref) async {
  final user = Supabase.instance.client.auth.currentUser;
  final metadata = Map<String, dynamic>.from(user?.userMetadata ?? const <String, dynamic>{});
  final normalizedRole = _normalizeRole(metadata);
  final expectedTable = normalizedRole == 'Doctor' ? 'doctor_profiles' : 'patient_records';
  final db = ref.read(databaseProvider);

  if (user == null) {
    return ProfileSyncDebugSnapshot(
      capturedAt: DateTime.now(),
      userId: null,
      email: null,
      metadata: metadata,
      normalizedRole: normalizedRole,
      expectedTable: expectedTable,
      foundInExpectedTable: false,
      foundInOtherTable: false,
      fullName: null,
      username: null,
      syncStatus: null,
      diagnosis: 'No authenticated user session.',
    );
  }

  final userId = user.id;

  Future<Map<String, Object?>?> getProfileRow(String table) async {
    final rows = await db
        .customSelect(
          'SELECT full_name, username, sync_status FROM $table WHERE user_id = ?',
          variables: [drift.Variable.withString(userId)],
        )
        .get();
    return rows.isNotEmpty ? rows.first.data : null;
  }


  final doctor = await getProfileRow('doctor_profiles');
  final patient = await getProfileRow('patient_records');

  final foundInExpectedTable =
      expectedTable == 'doctor_profiles' ? doctor != null : patient != null;
  final foundInOtherTable =
      expectedTable == 'doctor_profiles' ? patient != null : doctor != null;

  final activeRow = expectedTable == 'doctor_profiles' ? doctor : patient;
  final fullName = activeRow?['full_name']?.toString();
  final username = activeRow?['username']?.toString();
  final syncStatus = activeRow?['sync_status']?.toString();

  String diagnosis;
  if (!foundInExpectedTable) {
    diagnosis =
        'Missing local row in expected table. Check Supabase trigger and PowerSync download rules.';
  } else if (foundInOtherTable) {
    diagnosis =
        'User exists in both profile tables. Role mismatch between metadata and backend profile rows.';
  } else {
    diagnosis = 'Profile row found in expected table.';
  }

  return ProfileSyncDebugSnapshot(
    capturedAt: DateTime.now(),
    userId: user.id,
    email: user.email,
    metadata: metadata,
    normalizedRole: normalizedRole,
    expectedTable: expectedTable,
    foundInExpectedTable: foundInExpectedTable,
    foundInOtherTable: foundInOtherTable,
    fullName: fullName,
    username: username,
    syncStatus: syncStatus,
    diagnosis: diagnosis,
  );
}

final syncStatusProvider = StreamProvider<SyncStatus>((ref) async* {
  final powerSync = DatabaseManager.powersync;
  yield powerSync.currentStatus;
  yield* powerSync.statusStream;
});

final profileSyncDebugProvider =
    StreamProvider.autoDispose<ProfileSyncDebugSnapshot>((ref) async* {
  yield await _buildProfileSnapshot(ref);

  yield* Stream.periodic(const Duration(seconds: 3))
      .asyncMap((_) => _buildProfileSnapshot(ref));
});

