import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:uuid/uuid.dart';
import '../models/chat_models.dart';
import '../../../core/database/database_manager.dart' hide ChatMessage;
import '../services/chat_dao.dart';
import '../services/chat_service.dart';

final chatServiceProvider = Provider<ChatService>((ref) => ChatService());

final chatProvider = StateNotifierProvider<ChatNotifier, List<ChatMessage>>((ref) {
  return ChatNotifier(ref.read(chatServiceProvider));
});

class ChatNotifier extends StateNotifier<List<ChatMessage>> {
  final ChatService _chatService;
  final ChatDao _chatDao = ChatDao();
  StreamSubscription<AgentEvent>? _agentSubscription;
  StreamSubscription<List<ChatMessage>>? _dbSubscription;
  Timer? _timeoutTimer;

  String? _currentThreadId;
  String? _currentScanId;

  bool _isStreaming = false;
  String _agentAction = "";

  List<ChatMessage> _syncedMessages = [];
  List<ChatMessage> _inMemoryBubbles = [];
  int _targetSyncCount = -1;

  ChatNotifier(this._chatService) : super([]);

  bool get isStreaming => _isStreaming;
  String get agentAction => _agentAction;
  String? get currentThreadId => _currentThreadId;

  String get _currentUserId =>
      Supabase.instance.client.auth.currentUser?.id ?? 'anonymous_patient';

  void setScanContext(String? scanId) {
    _currentScanId = scanId;
  }

  void createNewSession() {
    _currentThreadId = null; // Will generate UUID on first message
    _dbSubscription?.cancel();
    _syncedMessages = [];
    _inMemoryBubbles = [];
    _targetSyncCount = -1;
    _isStreaming = false;
    _agentAction = "";
    _updateState();
  }

  void loadSession(String threadId) {
    _currentThreadId = threadId;
    _syncedMessages = [];
    _inMemoryBubbles = [];
    _targetSyncCount = -1;
    _isStreaming = false;
    _agentAction = "";

    _dbSubscription?.cancel();
    _dbSubscription = _chatDao.watchChatsForSession(threadId).listen((msgs) {
      _syncedMessages = msgs;
      
      // If we reached our target sync count, drop in-memory bubbles
      if (_targetSyncCount != -1 && _syncedMessages.length >= _targetSyncCount) {
        _inMemoryBubbles.clear();
        _targetSyncCount = -1;
        _timeoutTimer?.cancel();
      }
      
      _updateState();
    });
  }

  void _updateState() {
    state = [..._syncedMessages, ..._inMemoryBubbles];
  }

  void addUserMessage(String text) {
    _startExchange(text);
  }

  void retryMessage(String text) {
    _startExchange(text);
  }

  void _startExchange(String text) {
    if (_currentThreadId == null) {
      _currentThreadId = const Uuid().v4();
      loadSession(_currentThreadId!);
    }

    _agentSubscription?.cancel();
    _timeoutTimer?.cancel();

    _isStreaming = true;
    _agentAction = "Connecting to AI...";

    // Note the target sync count: current synced + user message (1) + AI reply (1)
    _targetSyncCount = _syncedMessages.length + 2;

    _inMemoryBubbles = [
      ChatMessage(
        id: const Uuid().v4(),
        threadId: _currentThreadId,
        text: text,
        isUser: true,
        createdAt: DateTime.now(),
      ),
      ChatMessage(
        id: 'streaming_ai',
        threadId: _currentThreadId,
        text: '',
        isUser: false,
        createdAt: DateTime.now(),
      ),
    ];
    _updateState();

    _agentSubscription = _chatService
        .streamAgentChat(
          text,
          _currentUserId,
          threadId: _currentThreadId!,
          currentScanId: _currentScanId,
        )
        .listen(
      (event) {
        switch (event) {
          case AgentTextEvent e:
            _agentAction = "";
            if (_inMemoryBubbles.length == 2) {
              final last = _inMemoryBubbles.last;
              _inMemoryBubbles[1] = last.copyWith(text: last.text + e.token);
              _updateState();
            }

          case AgentDoneEvent _:
            _isStreaming = false;
            _agentAction = "";
            // Stream is done, but keep bubbles until DB syncs them (or timeout)
            _startTimeoutTimer();
            _updateState();

          case AgentErrorEvent e:
            _markFailed('❌ ${e.message}');

          case AgentToolCallEvent _:
            break; // No-op

          case AgentUiTriggerEvent e:
            _agentAction = e.action;
            _updateState();

          case AgentKeepAliveEvent _:
            break;
        }
      },
      onError: (e) {
        _markFailed('❌ Connection error.');
      },
      onDone: () {
        if (_isStreaming) {
           _isStreaming = false;
           _agentAction = "";
           _startTimeoutTimer();
           _updateState();
        }
      },
    );
  }

  void _startTimeoutTimer() {
    _timeoutTimer?.cancel();
    _timeoutTimer = Timer(const Duration(seconds: 30), () {
      if (_targetSyncCount != -1) {
        _markFailed('❌ Not saved – Retry');
      }
    });
  }

  void _markFailed(String errorMsg) {
    _isStreaming = false;
    _agentAction = "";
    _targetSyncCount = -1;
    _timeoutTimer?.cancel();

    if (_inMemoryBubbles.length == 2) {
       final last = _inMemoryBubbles.last;
       final currentText = last.text;
       _inMemoryBubbles[1] = last.copyWith(
         text: currentText.isEmpty ? errorMsg : '$currentText\n\n$errorMsg'
       );
       _updateState();
    }
  }

  void stopStream() {
    _agentSubscription?.cancel();
    _agentSubscription = null;
    _isStreaming = false;
    _chatService.closeStream();
    _timeoutTimer?.cancel();
  }

  void clearChat() {
    state = [];
    _currentThreadId = null;
    _currentScanId = null;
    _isStreaming = false;
    _syncedMessages = [];
    _inMemoryBubbles = [];
    _dbSubscription?.cancel();
    _timeoutTimer?.cancel();
  }

  @override
  void dispose() {
    stopStream();
    _dbSubscription?.cancel();
    _timeoutTimer?.cancel();
    super.dispose();
  }
}