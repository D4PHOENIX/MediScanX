import 'package:drift/drift.dart';
// import 'package:drift/native.dart';
// import 'package:drift/wasm.dart';
// import 'package:sqlite3_flutter_libs/sqlite3_flutter_libs.dart';
// import 'package:sqlite3/sqlite3.dart';
// import 'package:path_provider/path_provider.dart';
// import 'package:path/path.dart' as p;
// import 'dart:io';

import 'package:flutter/foundation.dart';

import '../connection/native.dart'
  if (dart.library.js_interop) '../connection/web.dart';
part 'drift_database.g.dart';

// ==================== TABLES ====================

class PatientRecords extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get userId => text().unique()();
  TextColumn get userName => text().named('username')();
  TextColumn get fullName => text()();
  TextColumn get email => text()();
  TextColumn get phoneNumber => text()();
  TextColumn get gender => text().nullable()();
  TextColumn get dateOfBirth => text().named('date_of_birth').nullable()();
  IntColumn get age => integer().nullable()();
  TextColumn get location => text().nullable()();
  TextColumn get medicalHistory => text().nullable()();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
  TextColumn get syncStatus => text().withDefault(const Constant('pending'))();
}

class DoctorProfiles extends Table {
  IntColumn get id => integer().autoIncrement()();
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
  IntColumn get id => integer().autoIncrement()();
  TextColumn get scanId => text().unique()();
  TextColumn get userId => text()();
  IntColumn get scanType => integer()();
  IntColumn get scanStatus => integer()();
  TextColumn get imageUrl => text().nullable()();
  TextColumn get imagePath => text().nullable()();
  TextColumn get aiDiagnosis => text().nullable()();
  TextColumn get findings => text().nullable()();
  RealColumn get confidence => real().nullable()();
  TextColumn get metadata => text().nullable()();
  DateTimeColumn get scanDate => dateTime()();
  DateTimeColumn get createdAt => dateTime()();
  DateTimeColumn get updatedAt => dateTime()();
  TextColumn get syncStatus => text().withDefault(const Constant('pending'))();
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

// ==================== DATABASE ====================

@DriftDatabase(tables: [
  PatientRecords,
  ScanResults,
  DoctorProfiles,
  ChatMessages,
  AppSyncStatus,
])
class AppDatabase extends _$AppDatabase {
  AppDatabase(QueryExecutor e) : super(e);

  @override
  int get schemaVersion => 4;

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
      },
    );
  }

  // ==================== HELPER METHODS ====================

  // --- PATIENT METHODS ---
  Future<void> insertPatient(PatientRecordsCompanion patient) =>
      into(patientRecords).insertOnConflictUpdate(patient);

  Future<PatientRecord?> getPatient(String userId) =>
      (select(patientRecords)..where((tbl) => tbl.userId.equals(userId))).getSingleOrNull();

  Future<List<PatientRecord>> getAllPatients() =>
      select(patientRecords).get();

  // --- DOCTOR METHODS ---
  Future<void> insertDoctor(DoctorProfilesCompanion doctor) =>
      into(doctorProfiles).insertOnConflictUpdate(doctor);

  Future<DoctorProfile?> getDoctor(String userId) =>
      (select(doctorProfiles)..where((tbl) => tbl.userId.equals(userId))).getSingleOrNull();

  Future<List<DoctorProfile>> getAllDoctors() =>
      select(doctorProfiles).get();

  // --- SCAN METHODS ---
  Future<void> insertScan(ScanResultsCompanion scan) =>
      into(scanResults).insertOnConflictUpdate(scan);

  Future<ScanResult?> getScan(String scanId) =>
      (select(scanResults)..where((tbl) => tbl.scanId.equals(scanId))).getSingleOrNull();

  Future<List<ScanResult>> getScansByUser(String userId) =>
      (select(scanResults)..where((tbl) => tbl.userId.equals(userId))).get();

  Future<List<ScanResult>> getPendingScans() =>
      (select(scanResults)..where((tbl) => tbl.syncStatus.equals('pending'))).get();

  Future<void> updateScanSyncStatus(String scanId, String status) =>
      (update(scanResults)..where((tbl) => tbl.scanId.equals(scanId))).write(ScanResultsCompanion(syncStatus: Value(status)));

  // --- CHAT METHODS ---
  Future<void> insertMessage(ChatMessagesCompanion message) =>
      into(chatMessages).insertOnConflictUpdate(message);

  Future<List<ChatMessage>> getConversation(String sId, String rId) =>
      (select(chatMessages)..where((tbl) => (tbl.senderId.equals(sId) & tbl.recipientId.equals(rId)) | (tbl.senderId.equals(rId) & tbl.recipientId.equals(sId)))).get();

  Future<void> markMessageAsRead(int mId) =>
      (update(chatMessages)..where((tbl) => tbl.id.equals(mId))).write(const ChatMessagesCompanion(isRead: Value(true)));
}

// QueryExecutor _openConnection() {
//   // Check if we are running in a Web Browser
//   if (kIsWeb) {
//     return DatabaseConnection.delayed(
//       Future.sync(() async {
//         final result = await WasmDatabase.open(
//           databaseName: 'mediscanx_db',
//           sqlite3Uri: Uri.parse('sqlite3.wasm'),
//           driftWorkerUri: Uri.parse('drift_worker.js'),
//         );
//         return result.resolvedExecutor;
//       }),
//     );
//   }
//
//   // Native (Android/iOS/Windows) Connection
//   return LazyDatabase(() async {
//     final dbFolder = await getApplicationDocumentsDirectory();
//     final file = File(p.join(dbFolder.path, 'mediscanx.db'));
//
//     if (Platform.isAndroid) {
//       await applyWorkaroundToOpenSqlite3OnOldAndroidVersions();
//     }
//
//     final cachebase = await getTemporaryDirectory();
//     sqlite3.tempDirectory = cachebase.path;
//
//     return NativeDatabase(file);
//   });
// }