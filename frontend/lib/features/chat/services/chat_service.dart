import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../models/chat_models.dart';
import '../../../core/network/api_client.dart';
import 'package:http/http.dart' as http;

class ChatService {
  // Temporarily holds citations from a 'citations' event until the 'done' event arrives.
  final List<Citation> _pendingCitations = [];
  http.Client? _client;

  /// Starts a typed SSE stream with the LangGraph agent using manual HTTP.
  /// The backend SSE format uses the `event:` field for the type
  /// (e.g. `event: text`, `event: done`) and `data:` for the JSON payload.
  Stream<AgentEvent> streamAgentChat(
    String question,
    String patientId, {
    required String threadId,
    String? currentScanId,
  }) async* {
    debugPrint('💬 Starting SSE connection (manual http)...');
    _pendingCitations.clear();

    // Close any existing connection before starting a new one
    _client?.close();
    _client = http.Client();

    final session = Supabase.instance.client.auth.currentSession;
    final token = session?.accessToken;

    if (token == null || token.isEmpty) {
      debugPrint('🔴 CRITICAL: No auth token. User is not logged in.');
      yield const AgentErrorEvent('Authentication required.');
      return;
    }

    String step = '';
    final qLower = question.toLowerCase();

    if (qLower.contains('x-ray')) step = 'analyze_image';
    else if (qLower.contains('ecg')) step = 'analyze_ecg';
    else if (qLower.contains('skin')) step = 'analyze_skin';
    else if (qLower.contains('vitals')) step = 'review_metrics';
    else if (qLower.contains('temporal') || qLower.contains('changed since')) step = 'compare_scans';
    else if (qLower.contains('fusion')) step = 'fusion_analysis';

    final Map<String, dynamic> payload = {
      'messages': [
        {'role': 'user', 'content': question}
      ],
      'patient_id': patientId,
      'current_scan_id': currentScanId ?? '',
      'thread_id': threadId,
      'execution_step': step,
      'multimodal_metadata': {},
    };

    debugPrint('[ChatService] 📤 Payload: ${jsonEncode(payload)}');

    final request = http.Request(
      'POST',
      Uri.parse('${ApiConstants.baseUrl}/agent/chat'),
    )
      ..headers['Authorization'] = 'Bearer $token'
      ..headers['Content-Type'] = 'application/json'
      ..headers['Accept'] = 'text/event-stream'
      ..body = jsonEncode(payload);

    http.StreamedResponse response;

    try {
      response = await _client!.send(request);
      debugPrint('[ChatService] ✅ Backend responded with status ${response.statusCode}');

      if (response.statusCode != 200) {
        debugPrint('[ChatService] 🔴 Backend returned ${response.statusCode}');
        _client?.close();
        _client = null;
        yield AgentErrorEvent(
          'The AI server returned status ${response.statusCode}. Please try again.',
        );
        return;
      }
    } catch (e) {
      debugPrint('[ChatService] 🔴 Connection failed: $e');
      _client?.close();
      _client = null;
      yield AgentErrorEvent('Connection failed: $e');
      return;
    }

    // --- SSE Parser ---
    // Backend format:
    //   event: text|done|ui_trigger|citations|error
    //   data: { ... json ... }
    //   <blank line>
    //
    // The event TYPE lives in the SSE `event:` field, NOT inside the JSON body.
    String currentEvent = '';   // The SSE event type (e.g. "text", "done")
    String currentData = '';    // The JSON payload
    bool hasData = false;

    try {
      await for (final chunk in response.stream
          .transform(utf8.decoder)
          .transform(const LineSplitter())) {

        if (chunk.startsWith('event: ')) {
          // CAPTURE the event type — this is the discriminator
          currentEvent = chunk.substring(7).trim();
        } else if (chunk.startsWith('event:')) {
          currentEvent = chunk.substring(6).trim();
        } else if (chunk.startsWith('data: ')) {
          currentData = chunk.substring(6);
          hasData = true;
        } else if (chunk.startsWith('data:')) {
          currentData = chunk.substring(5).trimLeft();
          hasData = true;
        } else if (chunk.startsWith(':')) {
          // SSE comment / keepalive — ignore
          continue;
        } else if (chunk.isEmpty && hasData) {
          // Blank line = end of this SSE event — dispatch it

          // Guard: detect HTML error pages (Cloudflare 502, 503, etc.)
          if (currentData.trimLeft().startsWith('<') ||
              currentData.contains('<!DOCTYPE') ||
              currentData.contains('<html')) {
            debugPrint('[ChatService] 🔴 Received HTML instead of SSE.');
            yield const AgentErrorEvent(
              'The AI server is temporarily unreachable.',
            );
            break;
          }

          // Skip empty keepalive payloads
          if (currentData.isEmpty || currentData.trim() == 'keepalive') {
            hasData = false;
            currentData = '';
            currentEvent = '';
            continue;
          }

          yield _parseEvent(currentEvent, currentData);

          hasData = false;
          currentData = '';
          currentEvent = '';
        }
      }

      // If there's leftover data without a trailing blank line, process it
      if (hasData && currentData.isNotEmpty) {
        yield _parseEvent(currentEvent, currentData);
      }
    } catch (e) {
      debugPrint('[ChatService] ❌ Stream interrupted: $e');
      yield AgentErrorEvent('Stream interrupted: $e');
    } finally {
      _client?.close();
      _client = null;
      debugPrint('🛑 Chat SSE Stream finished.');
    }
  }

  /// Parses a single SSE event into a typed [AgentEvent].
  /// [sseEventType] is the value from the `event:` line (e.g. "text", "done").
  /// [rawData] is the value from the `data:` line (JSON string).
  AgentEvent _parseEvent(String sseEventType, String rawData) {
    try {
      final json = jsonDecode(rawData) as Map<String, dynamic>;

      // Use the SSE event: field as primary discriminator.
      // Fall back to json['type'] if the event: field was missing.
      final eventType = sseEventType.isNotEmpty
          ? sseEventType
          : (json['type'] as String? ?? '');

      debugPrint('[ChatService] 📨 SSE event=$sseEventType | JSON type=${json['type']} → resolved=$eventType');

      switch (eventType) {
        case 'text':
        case 'text_token':
          // Backend sends {"text": "..."} for text events
          final content = json['text'] as String? ?? json['content'] as String? ?? '';
          return AgentTextEvent(content);

        case 'tool_call':
          // Backend sends {"type":"tool_call", "tool":"...", "args":{...}}
          return AgentToolCallEvent(
            toolName: json['tool'] as String? ?? json['tool_name'] as String? ?? 'unknown_tool',
            input: (json['args'] as Map<String, dynamic>?) ??
                   (json['input'] as Map<String, dynamic>?) ?? {},
          );

        case 'ui_trigger':
          // Backend SSE event: ui_trigger, but JSON body may have type: tool_call
          final innerType = json['type'] as String? ?? '';
          if (innerType == 'tool_call') {
            return AgentToolCallEvent(
              toolName: json['tool'] as String? ?? json['tool_name'] as String? ?? 'unknown_tool',
              input: (json['args'] as Map<String, dynamic>?) ??
                     (json['input'] as Map<String, dynamic>?) ?? {},
            );
          }
          return AgentUiTriggerEvent(
            action: json['action'] as String? ?? innerType,
            payload: (json['payload'] as Map<String, dynamic>?) ?? json,
          );

        case 'citations':
          final sources = json['sources'] as List<dynamic>? ?? [];
          _pendingCitations
            ..clear()
            ..addAll(
              sources.map((s) => Citation.fromJson(s as Map<String, dynamic>)),
            );
          return const AgentKeepAliveEvent();

        case 'done':
          final citations = List<Citation>.from(_pendingCitations);
          _pendingCitations.clear();
          return AgentDoneEvent(
            citations: citations,
          );

        case 'error':
          return AgentErrorEvent(
            json['message'] as String? ?? json['error'] as String? ?? 'Unknown error from agent.',
          );

        default:
          debugPrint('[ChatService] Unhandled event type: $eventType — data: $rawData');
          return const AgentKeepAliveEvent();
      }
    } catch (e) {
      debugPrint(
        '[ChatService] ❌ Failed to parse SSE event: $rawData — Error: $e',
      );
      return const AgentKeepAliveEvent();
    }
  }

  /// Call when the user leaves the chat screen or the agent finishes.
  void closeStream() {
    _client?.close();
    _client = null;
    _pendingCitations.clear();
    debugPrint('🛑 Chat SSE Stream Closed.');
  }
}