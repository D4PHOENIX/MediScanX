// lib/features/chat/services/chat_dao.dart
import 'dart:convert';
import 'package:drift/drift.dart';
import '../models/chat_models.dart';
import '../../../core/config/drift_database.dart' hide ChatMessage;

class ChatDao {
  final AppDatabase db;
  ChatDao(this.db);

  /// Fetch all previous chats for a specific patient, ordered by time
  Future<List<ChatMessage>> getChatsForPatient(String patientId) async {
    final rows = await db.customSelect(
      'SELECT * FROM langchain_chat_histories WHERE patient_id = ? ORDER BY created_at ASC',
      variables: [Variable.withString(patientId)],
    ).get();

    return rows.map((row) {
      // 1. Safely parse the citations JSON string back into a List<Citation>
      List<Citation>? parsedCitations;
      final citationsJson = row.read<String?>('citations');

      if (citationsJson != null && citationsJson.isNotEmpty) {
        try {
          final List<dynamic> decoded = jsonDecode(citationsJson);
          parsedCitations = decoded.map((c) => Citation.fromJson(c)).toList();
        } catch (e) {
          parsedCitations = [];
        }
      }

      // 2. Map the SQLite row back to your Flutter model
      return ChatMessage(
        id: row.read<String>('id'),
        text: row.read<String>('text'),
        isUser: row.read<int>('is_user') == 1,
        createdAt: DateTime.parse(row.read<String>('created_at')),
        citations: parsedCitations,
      );
    }).toList();
  }

  /// Save a new message locally (PowerSync automatically syncs this to Supabase)
  Future<void> insertChat(ChatMessage message, String patientId) async {
    // Convert citations list to a JSON string for SQLite storage
    final citationsJson = message.citations != null
        ? jsonEncode(message.citations!.map((c) => {
      'source_id': c.sourceId,
      'snippet': c.snippet,
      'relevance_score': c.relevanceScore,
    }).toList())
        : null;

    await db.customInsert(
      'INSERT OR IGNORE INTO langchain_chat_histories (id, patient_id, text, is_user, created_at, citations) '
          'VALUES (?, ?, ?, ?, ?, ?)',
      variables: [
        Variable.withString(message.id),
        Variable.withString(patientId),
        Variable.withString(message.text),
        Variable.withInt(message.isUser ? 1 : 0),
        Variable.withString(message.createdAt.toIso8601String()),
        Variable<String>(citationsJson),
      ],
    );
  }
}