import 'package:powersync/powersync.dart';

// Note: PowerSync automatically creates an 'id' (UUID) primary key column
// for every table behind the scenes to match Supabase. We only need to define
// the custom data columns.

const patientRecordsTable = Table('patient_records', [
  Column.text('user_id'),
  Column.text('username'),
  Column.text('full_name'),
  Column.text('email'),
  Column.text('phone_number'),
  Column.text('gender'),
  Column.text('date_of_birth'),
  Column.text('location'),
  Column.text('medical_history'), // JSON strings are stored as text
  Column.text('created_at'),      // DateTimes are stored as ISO8601 text
  Column.text('updated_at'),
  Column.text('sync_status'),
]);

const scanResultsTable = Table('scan_results', [
  Column.text('scan_id'),
  Column.text('user_id'),
  Column.integer('scan_type'),
  Column.integer('scan_status'),
  Column.text('image_url'),
  Column.text('modality'),
  Column.text('xai_path'),
  Column.text('xai_status'),
  Column.text('ai_diagnosis'),
  Column.text('findings'),
  Column.real('confidence'),      // 'real' is used for doubles/decimals
  Column.text('metadata'),
  Column.text('scan_date'),
  Column.text('created_at'),
  Column.text('updated_at'),
  Column.text('sync_status'),
]);

const doctorProfilesTable = Table('doctor_profiles', [
  Column.text('user_id'),
  Column.text('full_name'),
  Column.text('email'),
  Column.text('username'),
  Column.text('specialization'),
  Column.text('current_hospital'),
  Column.text('phone_number'),
  Column.text('license_number'),
  Column.text('biography'),
  Column.text('gender'),
  Column.text('date_of_birth'),
  Column.integer('age'),
  Column.text('created_at'),
  Column.text('updated_at'),
  Column.text('sync_status'),
]);

// Used for human-to-human messaging (Doctor <-> Patient)
const chatMessagesTable = Table('chat_messages', [
  Column.text('message_id'),
  Column.text('sender_id'),
  Column.text('recipient_id'),
  Column.text('message'),
  Column.integer('message_type'),
  Column.text('sent_at'),
  Column.integer('is_read'), // SQLite stores booleans as 0 or 1 integers
  Column.text('sync_status'),
]);

// --- NEW: AI Chat History Table ---
// Matches the LangGraph backend table specifically for the RAG agent
const langchainChatHistoriesTable = Table('langchain_chat_histories', [
  Column.text('patient_id'),
  Column.text('text'),
  Column.integer('is_user'), // 1 for User, 0 for AI
  Column.text('created_at'),
  Column.text('citations'),  // Store the list of citations as a JSON string
]);

// Offline edge inference outbox — stores results from TFLite that
// haven't been uploaded to the cloud API yet (uploaded by EdgeOutboxService)
const pendingSyncScansTable = Table('pending_sync_scans', [
  Column.text('user_id'),
  Column.text('scan_type'),    // 'cxr', 'ecg', 'skin'
  Column.text('image_path'),   // LOCAL device file path — never synced to Supabase
  Column.text('metadata'),     // JSON blob of TFLite findings
  Column.text('created_at'),
  Column.integer('retry_count'),
  Column.text('sync_status'),  // 'pending', 'uploading', 'done', 'failed'
], viewName: 'pending_sync_scans');

// Bundle them all into the final Schema object that the engine will read
const appSchema = Schema([
  patientRecordsTable,
  scanResultsTable,
  doctorProfilesTable,
  chatMessagesTable,
  langchainChatHistoriesTable, // Added to the sync engine
  pendingSyncScansTable,
]);