// lib/features/chat/models/chat_models.dart

class ChatMessage {
  final String id;
  final String? threadId;
  final String text;
  final bool isUser;
  final DateTime createdAt;
  final List<Citation>? citations;

  ChatMessage({
    required this.id,
    this.threadId,
    required this.text,
    required this.isUser,
    required this.createdAt,
    this.citations,
  });

  // Optional: A quick copyWith method in case you need to update a message later
  ChatMessage copyWith({
    String? id,
    String? threadId,
    String? text,
    bool? isUser,
    DateTime? createdAt,
    List<Citation>? citations,
  }) {
    return ChatMessage(
      id: id ?? this.id,
      threadId: threadId ?? this.threadId,
      text: text ?? this.text,
      isUser: isUser ?? this.isUser,
      createdAt: createdAt ?? this.createdAt,
      citations: citations ?? this.citations,
    );
  }
}

class ChatSession {
  final String id;
  final String title;
  final String lastMessagePreview;
  final DateTime updatedAt;

  ChatSession({
    required this.id,
    required this.title,
    required this.lastMessagePreview,
    required this.updatedAt,
  });
}

class Citation {
  final String sourceId;
  final String snippet;
  final double relevanceScore;

  Citation({
    required this.sourceId,
    required this.snippet,
    required this.relevanceScore,
  });

  // Helper to parse citations coming from the AI stream (if needed later)
  factory Citation.fromJson(Map<String, dynamic> json) {
    return Citation(
      sourceId: json['source_id'] ?? 'Unknown Source',
      snippet: json['snippet'] ?? '',
      relevanceScore: (json['relevance_score'] ?? 0.0).toDouble(),
    );
  }
}

// ==================== AGENT SSE EVENT TYPES ====================
// Sealed class hierarchy for the typed LangGraph SSE event stream.
// Each SSE data packet maps to exactly one of these subtypes.

sealed class AgentEvent {
  const AgentEvent();
}

/// A raw text token streamed from the LLM (append to the current AI bubble).
class AgentTextEvent extends AgentEvent {
  final String token;
  const AgentTextEvent(this.token);
}

/// The agent called a backend tool (e.g., search_medline, retrieve_scan).
class AgentToolCallEvent extends AgentEvent {
  final String toolName;
  final Map<String, dynamic> input;
  const AgentToolCallEvent({required this.toolName, required this.input});
}

/// The agent wants the UI to do something (e.g., show a scan card).
class AgentUiTriggerEvent extends AgentEvent {
  final String action;
  final Map<String, dynamic> payload;
  const AgentUiTriggerEvent({required this.action, required this.payload});
}

/// The agent finished the turn.
class AgentDoneEvent extends AgentEvent {
  final List<Citation> citations;
  const AgentDoneEvent({required this.citations});
}

/// The server returned an error.
class AgentErrorEvent extends AgentEvent {
  final String message;
  const AgentErrorEvent(this.message);
}

/// A keepalive ping from the server — safe to ignore.
class AgentKeepAliveEvent extends AgentEvent {
  const AgentKeepAliveEvent();
}