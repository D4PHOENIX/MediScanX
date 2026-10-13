import 'dart:convert';
import '../../../core/database/database_manager.dart';
import '../models/chat_models.dart';

class ChatDao {
  /// Fetch all chat sessions for a specific patient.
  /// Uses a watch query so the UI updates as sync completes.
  Stream<List<ChatSession>> watchChatSessionsForPatient(String patientId) {
    final query = '''
      SELECT m.thread_id,
             MIN(m.created_at) AS started_at,
             MAX(m.created_at) AS last_at,
             (SELECT f.text FROM chat_messages f
               WHERE f.thread_id = m.thread_id AND f.is_user = 1
               ORDER BY f.created_at ASC LIMIT 1) AS title,
             (SELECT a.text FROM chat_messages a
               WHERE a.thread_id = m.thread_id AND a.is_user = 0
               ORDER BY a.created_at DESC LIMIT 1) AS preview
      FROM chat_messages m
      WHERE m.patient_id = ?
      GROUP BY m.thread_id
      ORDER BY last_at DESC
    ''';

    return DatabaseManager.powersync.watch(query, parameters: [patientId]).map((rows) {
      return rows.map((row) {
        final threadId = row['thread_id'] as String;
        
        String title = "New Conversation";
        final rawTitle = row['title'];
        if (rawTitle != null) {
          title = _parseMessageText(rawTitle);
          if (title.startsWith('I just completed a ')) {
            final match = RegExp(r'I just completed a (.*?) scan').firstMatch(title);
            if (match != null) {
              title = "${match.group(1)} Analysis";
            } else {
              title = "Diagnostic Analysis";
            }
          } else if (title.startsWith('About my ')) {
            final match = RegExp(r'About my (.*?):').firstMatch(title);
            if (match != null) {
              title = match.group(1) ?? "Scan Analysis";
            } else {
              title = "Scan Analysis";
            }
          } else {
            title = title.replaceAll('\n', ' ').trim();
            if (title.length > 40) title = '${title.substring(0, 40)}...';
          }
        }

        String preview = "";
        final rawPreview = row['preview'];
        if (rawPreview != null) {
          preview = _parseMessageText(rawPreview);
          preview = preview.replaceAll('\n', ' ').trim();
          if (preview.length > 50) preview = '${preview.substring(0, 50)}...';
        }

        final lastAtStr = row['last_at'] as String?;
        final updatedAt = _parseTimestamp(lastAtStr);

        return ChatSession(
          id: threadId,
          title: title,
          lastMessagePreview: preview,
          updatedAt: updatedAt,
        );
      }).toList();
    });
  }

  /// Fetch all previous chats for a specific thread, ordered by time
  Stream<List<ChatMessage>> watchChatsForSession(String threadId) {
    final query = 'SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY created_at ASC';
    
    return DatabaseManager.powersync.watch(query, parameters: [threadId]).map((rows) {
      return rows.map((row) {
        // 1. Parse Citations
        List<Citation>? parsedCitations;
        final citationsRaw = row['citations'];
        if (citationsRaw != null) {
          if (citationsRaw is String) {
            try {
              final List<dynamic> decoded = jsonDecode(citationsRaw);
              parsedCitations = decoded.map((c) => Citation.fromJson(c)).toList();
            } catch (_) { parsedCitations = []; }
          }
        }

        // 2. Parse Text
        final rawText = row['text'];
        String parsedText = _parseMessageText(rawText);

        // 3. Parse is_user
        bool isUser = false;
        if (row['is_user'] is int) {
          isUser = row['is_user'] == 1;
        }

        // 4. Map to Model
        return ChatMessage(
          id: row['id']?.toString() ?? '',
          threadId: threadId,
          text: parsedText,
          isUser: isUser,
          createdAt: _parseTimestamp(row['created_at']?.toString()),
          citations: parsedCitations,
        );
      }).toList();
    });
  }

  /// Delete a chat, inside a write transaction
  Future<void> deleteChat(String threadId) async {
    await DatabaseManager.powersync.writeTransaction((tx) async {
      await tx.execute('DELETE FROM chat_messages WHERE thread_id = ?', [threadId]);
    });
  }

  DateTime _parseTimestamp(String? timestamp) {
    if (timestamp == null || timestamp.isEmpty) return DateTime.now();
    String clean = timestamp.trim();
    if (!clean.endsWith('Z') && !clean.contains('+')) {
      clean = clean.replaceAll(' ', 'T') + 'Z';
    }
    return DateTime.tryParse(clean)?.toLocal() ?? DateTime.now();
  }

  /// Helper to parse the message text which might be a LangGraph JSON array
  String _parseMessageText(dynamic rawText) {
    if (rawText == null) return '';
    
    if (rawText is String) {
      if (rawText.trim().startsWith('[')) {
        try {
          final List<dynamic> parsed = jsonDecode(rawText);
          return parsed.map((e) => e['text']?.toString() ?? '').join('');
        } catch (e) {
          return rawText;
        }
      }
      return rawText;
    }
    
    return rawText.toString();
  }
}