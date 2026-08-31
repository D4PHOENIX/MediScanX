import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../models/chat_models.dart';
import '../../../core/database/database_manager.dart' hide ChatMessage;
import '../services/chat_dao.dart';
import '../services/chat_service.dart';

final chatServiceProvider = Provider<ChatService>((ref) => ChatService());

final chatProvider = StateNotifierProvider<ChatNotifier, List<ChatMessage>>((ref) {
  return ChatNotifier(ref.read(chatServiceProvider))..loadHistory();
});

class ChatNotifier extends StateNotifier<List<ChatMessage>> {
  final ChatService _chatService;
  final ChatDao _chatDao = ChatDao(DatabaseManager.drift);
  StreamSubscription<AgentEvent>? _agentSubscription;
  String? _currentSessionId; // Tracks LangGraph session for multi-turn continuity
  String? _currentScanId;    // UUID of the scan currently being discussed

  ChatNotifier(this._chatService) : super([]);

  String get _currentUserId =>
      Supabase.instance.client.auth.currentUser?.id ?? 'anonymous_patient';

  /// Call this when opening the chat screen from a diagnostic result screen.
  /// Sets the scan context so the agent knows which scan is being discussed.
  void setScanContext(String? scanId) {
    _currentScanId = scanId;
    debugPrint('[Chat] 🪤 Scan context set: $_currentScanId');
  }

  /// Loads previous chat history from local SQLite
  Future<void> loadHistory() async {
    final history = await _chatDao.getChatsForPatient(_currentUserId);
    state = history;
  }

  /// Appends and persists a user message
  void addUserMessage(String text) {
    final message = ChatMessage(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      text: text,
      isUser: true,
      createdAt: DateTime.now(),
    );
    state = [...state, message];
    _chatDao.insertChat(message, _currentUserId);
  }

  /// Appends and persists a final AI message (for non-streaming use)
  void addAIMessage(String text) {
    final message = ChatMessage(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      text: text,
      isUser: false,
      createdAt: DateTime.now(),
    );
    state = [...state, message];
    _chatDao.insertChat(message, _currentUserId);
  }

  /// Starts a streaming agent response. Creates an empty AI bubble and fills it
  /// token by token as the SSE stream delivers chunks.
  void startAgentStream(String question) {
    // Cancel any in-flight stream before starting a new one
    _agentSubscription?.cancel();

    // Append an empty AI message placeholder that we'll fill incrementally
    final streamingId = 'streaming_${DateTime.now().millisecondsSinceEpoch}';
    final emptyAiMessage = ChatMessage(
      id: streamingId,
      text: '',
      isUser: false,
      createdAt: DateTime.now(),
    );
    state = [...state, emptyAiMessage];

    _agentSubscription = _chatService
        .streamAgentChat(
          question,
          _currentUserId,
          sessionId: _currentSessionId,
          currentScanId: _currentScanId, // Forward active scan UUID to agent
        )
        .listen(
      (event) {
        switch (event) {
          case AgentTextEvent():
            // Append token to the last message in state
            final updated = List<ChatMessage>.from(state);
            if (updated.isNotEmpty) {
              final last = updated.last;
              updated[updated.length - 1] = last.copyWith(text: last.text + event.token);
              state = updated;
            }

          case AgentDoneEvent():
            // Store session ID for next turn
            _currentSessionId = event.sessionId.isNotEmpty ? event.sessionId : _currentSessionId;
            // Persist the final completed message to DB
            if (state.isNotEmpty) {
              final finalMsg = state.last.copyWith(
                id: DateTime.now().millisecondsSinceEpoch.toString(),
                citations: event.citations.isNotEmpty ? event.citations : null,
              );
              _chatDao.insertChat(finalMsg, _currentUserId);
              // Update state with persisted ID
              final updated = List<ChatMessage>.from(state);
              updated[updated.length - 1] = finalMsg;
              state = updated;
            }
            debugPrint('[Chat] ✅ Agent turn complete. Session: $_currentSessionId');

          case AgentErrorEvent():
            // Show error message in the bubble
            if (state.isNotEmpty) {
              final updated = List<ChatMessage>.from(state);
              updated[updated.length - 1] = updated.last.copyWith(
                text: '❌ ${event.message}',
              );
              state = updated;
            }
            debugPrint('[Chat] ❌ Agent error: ${event.message}');

          case AgentToolCallEvent():
            debugPrint('[Chat] 🔧 Tool call: ${event.toolName} with ${event.input}');

          case AgentUiTriggerEvent():
            debugPrint('[Chat] 🖼️ UI trigger: ${event.action} — ${event.payload}');

          case AgentKeepAliveEvent():
            break; // No-op
        }
      },
      onError: (e) {
        debugPrint('[Chat] Stream error: $e');
        if (state.isNotEmpty) {
          final updated = List<ChatMessage>.from(state);
          updated[updated.length - 1] = updated.last.copyWith(text: '❌ Connection error.');
          state = updated;
        }
      },
      onDone: () => debugPrint('[Chat] SSE stream closed.'),
    );
  }

  /// Stops any active stream subscription
  void stopStream() {
    _agentSubscription?.cancel();
    _agentSubscription = null;
    _chatService.closeStream();
  }

  /// Clears the UI without deleting DB history
  void clearChat() {
    state = [];
    _currentSessionId = null;
    _currentScanId = null;
  }

  @override
  void dispose() {
    stopStream();
    super.dispose();
  }
}