import 'package:drift/drift.dart';
import '../connection/native.dart'
  if (dart.library.js_interop) '../connection/web.dart';
part 'drift_database.g.dart';

// ==================== TABLES ====================

class PatientRecords extends Table {
  TextColumn get id => text()();
  TextColumn get userId => text().unique()();
  TextColumn get userName => text().named('username')();
  TextColumn get fullName => text()();
  TextColumn get email => text()();
  TextColumn get phoneNumber => text()();
  TextColumn get gender => text().nullable()();
  TextColumn get dateOfBirth => text().named('date_of_birth').nullable()();
  TextColumn get location => text().nullable()();
  TextColumn get medicalHistory => text().nullable()();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
  TextColumn get syncStatus => text().withDefault(const Constant('pending'))();
}

class DoctorProfiles extends Table {
  TextColumn get id => text()();
  TextColumn get userId => text().unique()();
  TextColumn get userName => text().named('username')();
  TextColumn get fullName => text()();
  TextColumn get email => text()();
  TextColumn get phoneNumber => text().nullable()();
  TextColumn get gender => text().nullable()();
  TextColumn get dateOfBirth => text().named('date_of_birth').nullable()();
  IntColumn get age => integer().nullable()();
  TextColumn get specialization => text()();
  TextColumn get currentHospital => text()();
  TextColumn get licenseNumber => text().nullable()();
  TextColumn get biography => text().nullable()();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
  TextColumn get syncStatus => text().withDefault(const Constant('pending'))();
}

class ScanResults extends Table {
  TextColumn get id => text()();
  TextColumn get scanId => text().nullable().unique()();
  TextColumn get userId => text()();
  IntColumn get scanType => integer()();
  IntColumn get scanStatus => integer()();
  TextColumn get imageUrl => text().nullable()();
  TextColumn get modality => text().nullable()(); // 'cxr', 'ecg', 'skin'
  TextColumn get xaiPath => text().nullable()();
  TextColumn get xaiStatus => text().nullable()(); // 'generated', 'failed', 'none', 'skipped_edge'
  TextColumn get aiDiagnosis => text().nullable()();
  TextColumn get findings => text().nullable()();
  RealColumn get confidence => real().nullable()();
  TextColumn get metadata => text().nullable()();
  DateTimeColumn get scanDate => dateTime()();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
  TextColumn get syncStatus => text().nullable().withDefault(const Constant('pending'))();
}

class ChatMessages extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get messageId => text().unique()();
  TextColumn get senderId => text()();
  TextColumn get recipientId => text()();
  TextColumn get message => text()();
  IntColumn get messageType => integer().withDefault(const Constant(0))();
  DateTimeColumn get sentAt => dateTime()();
  BoolColumn get isRead => boolean().withDefault(const Constant(false))();
  TextColumn get syncStatus => text().withDefault(const Constant('pending'))();
}

class AppSyncStatus extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get entityType => text()();
  TextColumn get entityId => text()();
  IntColumn get syncAction => integer()();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get lastSyncAttempt => dateTime().nullable()();
  IntColumn get syncAttempts => integer().withDefault(const Constant(0))();
}

class PendingSyncScans extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get userId => text()();
  TextColumn get scanType => text()(); // 'cxr', 'ecg', 'skin'
  TextColumn get imagePath => text()(); // Local device path
  TextColumn get metadata => text()(); // JSON blob of TFLite findings
  DateTimeColumn get createdAt => dateTime()();
  IntColumn get retryCount => integer().withDefault(const Constant(0))();
  TextColumn get syncStatus => text().withDefault(const Constant('pending'))();
}

// ==================== DATABASE ====================

@DriftDatabase(tables: [
  PatientRecords,
  ScanResults,
  DoctorProfiles,
  ChatMessages,
  AppSyncStatus,
  PendingSyncScans,
])
class AppDatabase extends _$AppDatabase {
  AppDatabase(QueryExecutor e) : super(e);

  @override
  int get schemaVersion => 7;

  Future<bool> _hasColumn(String tableName, String columnName) async {
    final rows = await customSelect('PRAGMA table_info(' + tableName + ')').get();
    return rows.any((row) => row.data['name'] == columnName);
  }

  @override
  MigrationStrategy get migration {
    return MigrationStrategy(
      onCreate: (Migrator m) async {
        await m.createAll();
      },
      onUpgrade: (Migrator m, int from, int to) async {
        if (from == 1) {
          await m.addColumn(patientRecords, patientRecords.userName);
          await m.addColumn(doctorProfiles, doctorProfiles.userName);
          await m.addColumn(doctorProfiles, doctorProfiles.phoneNumber);
          await m.addColumn(doctorProfiles, doctorProfiles.gender);
          await m.addColumn(doctorProfiles, doctorProfiles.age);
        }

        if (from < 3) {
          if (await _hasColumn('patient_records', 'user_name') &&
              !(await _hasColumn('patient_records', 'username'))) {
            await customStatement(
              'ALTER TABLE patient_records RENAME COLUMN user_name TO username',
            );
          }

          if (await _hasColumn('doctor_profiles', 'user_name') &&
              !(await _hasColumn('doctor_profiles', 'username'))) {
            await customStatement(
              'ALTER TABLE doctor_profiles RENAME COLUMN user_name TO username',
            );
          }
        }

        if (from < 4) {
          if (!(await _hasColumn('patient_records', 'date_of_birth'))) {
            await m.addColumn(patientRecords, patientRecords.dateOfBirth);
          }

          if (!(await _hasColumn('doctor_profiles', 'date_of_birth'))) {
            await m.addColumn(doctorProfiles, doctorProfiles.dateOfBirth);
          }
        }

        if (from < 5) {
          if (await _hasColumn('scan_results', 'image_path')) {
            await customStatement('ALTER TABLE scan_results DROP COLUMN image_path');
          }
          if (!(await _hasColumn('scan_results', 'image_url'))) {
            await m.addColumn(scanResults, scanResults.imageUrl);
          }
          await m.createTable(pendingSyncScans);
        }

        if (from < 6) {
          if (!(await _hasColumn('scan_results', 'modality'))) {
            await m.addColumn(scanResults, scanResults.modality);
          }
        }

        if (from < 7) {
          if (!(await _hasColumn('scan_results', 'xai_path'))) {
            await m.addColumn(scanResults, scanResults.xaiPath);
          }
          if (!(await _hasColumn('scan_results', 'xai_status'))) {
            await m.addColumn(scanResults, scanResults.xaiStatus);
          }
        }
      },
    );
  }

  // ==================== HELPER METHODS ====================

  // --- PATIENT METHODS ---
  Future<void> insertPatient(PatientRecordsCompanion patient) =>
      into(patientRecords).insert(patient);

  Future<PatientRecord?> getPatient(String userId) =>
      (select(patientRecords)..where((tbl) => tbl.userId.equals(userId))).getSingleOrNull();

  Future<List<PatientRecord>> getAllPatients() =>
      select(patientRecords).get();

  // --- DOCTOR METHODS ---
  Future<void> insertDoctor(DoctorProfilesCompanion doctor) =>
      into(doctorProfiles).insert(doctor);

  Future<DoctorProfile?> getDoctor(String userId) =>
      (select(doctorProfiles)..where((tbl) => tbl.userId.equals(userId))).getSingleOrNull();

  Future<List<DoctorProfile>> getAllDoctors() =>
      select(doctorProfiles).get();

  // --- SCAN METHODS ---
  Future<void> insertScan(ScanResultsCompanion scan) =>
      into(scanResults).insert(scan);

  Future<ScanResult?> getScan(String scanId) =>
      (select(scanResults)..where((tbl) => tbl.scanId.equals(scanId))).getSingleOrNull();

  Future<List<ScanResult>> getScansByUser(String userId) =>
      (select(scanResults)..where((tbl) => tbl.userId.equals(userId))).get();

  Future<List<ScanResult>> getAllScans() =>
      select(scanResults).get();

  Future<List<ScanResult>> getPendingScans() =>
      (select(scanResults)..where((tbl) => tbl.syncStatus.equals('pending'))).get();

  Future<void> updateScanSyncStatus(String scanId, String status) =>
      (update(scanResults)..where((tbl) => tbl.scanId.equals(scanId))).write(ScanResultsCompanion(syncStatus: Value(status)));

  // --- CHAT METHODS ---
  Future<void> insertMessage(ChatMessagesCompanion message) =>
      into(chatMessages).insert(message);

  Future<List<ChatMessage>> getConversation(String sId, String rId) =>
      (select(chatMessages)..where((tbl) => (tbl.senderId.equals(sId) & tbl.recipientId.equals(rId)) | (tbl.senderId.equals(rId) & tbl.recipientId.equals(sId)))).get();

  Future<void> markMessageAsRead(int mId) =>
      (update(chatMessages)..where((tbl) => tbl.id.equals(mId))).write(const ChatMessagesCompanion(isRead: Value(true)));

  // --- PENDING SYNC METHODS ---
  Future<List<PendingSyncScan>> getPendingOutboxScans() =>
      (select(pendingSyncScans)..where((tbl) => tbl.syncStatus.equals('pending'))).get();

  Future<void> insertPendingScan(PendingSyncScansCompanion scan) =>
      into(pendingSyncScans).insert(scan);

  Future<void> updateOutboxScanStatus(int id, String status, int retries) =>
      (update(pendingSyncScans)..where((tbl) => tbl.id.equals(id))).write(
        PendingSyncScansCompanion(
          syncStatus: Value(status),
          retryCount: Value(retries),
        ),
      );
}
