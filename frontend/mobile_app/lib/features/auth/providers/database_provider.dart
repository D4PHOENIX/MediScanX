import 'package:riverpod/riverpod.dart';
// Ensure this path matches where you created your drift_database.dart
import '../../../core/config/drift_database.dart';
import '../../../core/database/database_manager.dart';

/// 1. Database Instance Provider
/// Provides a single, global instance of the AppDatabase.
final databaseProvider = Provider<AppDatabase>((ref) {
  return DatabaseManager.drift;
});

/// 2. Patient Records Repository Provider
final patientRepositoryProvider = Provider<PatientRepository>((ref) {
  final db = ref.watch(databaseProvider);
  return PatientRepository(db);
});

/// 3. Scan Results Repository Provider
final scanRepositoryProvider = Provider<ScanRepository>((ref) {
  final db = ref.watch(databaseProvider);
  return ScanRepository(db);
});

/// 4. Chat Messages Repository Provider
final chatRepositoryProvider = Provider<ChatRepository>((ref) {
  final db = ref.watch(databaseProvider);
  return ChatRepository(db);
});

// ==========================================
// REPOSITORIES
// ==========================================

class PatientRepository {
  final AppDatabase db;
  PatientRepository(this.db);

  Future<void> insertPatient(PatientRecordsCompanion patient) =>
      db.insertPatient(patient);

  Future<PatientRecord?> getPatient(String userId) =>
      db.getPatient(userId);

  Future<List<PatientRecord>> getAllPatients() =>
      db.getAllPatients();
}

class ScanRepository {
  final AppDatabase db;
  ScanRepository(this.db);

  Future<void> insertScan(ScanResultsCompanion scan) =>
      db.insertScan(scan);

  Future<ScanResult?> getScan(String scanId) =>
      db.getScan(scanId);

  Future<List<ScanResult>> getScansByUser(String userId) =>
      db.getScansByUser(userId);

  Future<List<ScanResult>> getPendingScans() =>
      db.getPendingScans();

  Future<void> updateScanSyncStatus(String scanId, String status) =>
      db.updateScanSyncStatus(scanId, status);
}

class ChatRepository {
  final AppDatabase db;
  ChatRepository(this.db);

  Future<void> insertMessage(ChatMessagesCompanion message) =>
      db.insertMessage(message);

  Future<List<ChatMessage>> getConversation(String senderId, String recipientId) =>
      db.getConversation(senderId, recipientId);

  Future<void> markMessageAsRead(int messageId) =>
      db.markMessageAsRead(messageId);
}