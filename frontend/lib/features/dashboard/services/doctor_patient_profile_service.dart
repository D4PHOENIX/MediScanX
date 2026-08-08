import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:drift/drift.dart';
import 'package:mediscanx_mobile/core/config/drift_database.dart';
import 'package:mediscanx_mobile/features/auth/providers/database_provider.dart';
import 'package:uuid/uuid.dart';

final doctorPatientProfileServiceProvider = Provider<DoctorPatientProfileService>((ref) {
  return DoctorPatientProfileService(ref.read(databaseProvider));
});

class DoctorPatientProfileService {
  final AppDatabase _db;

  DoctorPatientProfileService(this._db);

  /// Checks if a doctor has an associated patient profile
  Future<bool> hasPatientProfile(String userId) async {
    final patientRecord = await _db.getPatient(userId);
    return patientRecord != null;
  }

  /// Creates a patient profile for a doctor by copying their details
  Future<void> createPatientProfileForDoctor(DoctorProfile doctor) async {
    final now = DateTime.now().toIso8601String();
    
    await _db.customInsert(
      '''
      INSERT INTO patient_records 
      (id, user_id, username, full_name, email, phone_number, gender, date_of_birth, created_at, updated_at, sync_status) 
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ''',
      variables: [
        Variable.withString(doctor.userId), // Set local PowerSync id to the exact user_id UUID
        Variable.withString(doctor.userId),
        Variable.withString(doctor.userName),
        Variable.withString(doctor.fullName),
        Variable.withString(doctor.email),
        Variable.withString(doctor.phoneNumber ?? ''),
        Variable.withString(doctor.gender ?? ''),
        Variable.withString(doctor.dateOfBirth ?? ''),
        Variable.withString(now),
        Variable.withString(now),
        Variable.withString('pending'),
      ],
      updates: {_db.patientRecords},
    );
  }
}
