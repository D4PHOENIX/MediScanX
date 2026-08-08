import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_client_sse/constants/sse_request_type_enum.dart';
import 'package:flutter_client_sse/flutter_client_sse.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../models/chat_models.dart';
import '../../../core/network/api_client.dart';
import 'package:http/http.dart' as http;

class ChatService {
  // Temporarily holds citations from a 'citations' event until the 'done' event arrives.
  final List<Citation> _pendingCitations = [];

  /// Starts a typed SSE stream with the LangGraph agent.
  /// The UI listens to [AgentEvent] subtypes and reacts accordingly.
  /// Pass [sessionId] to continue a previous conversation turn.
  Stream<AgentEvent> streamAgentChat(
    String question,
    String patientId, {
    String? sessionId,
    String? currentScanId, // UUID of the scan being discussed
  }) {
    debugPrint('💬 Starting SSE connection to LangGraph Agent...');
    _pendingCitations.clear();

    final session = Supabase.instance.client.auth.currentSession;
    final token = session?.accessToken;

    if (token == null || token.isEmpty) {
      debugPrint('🔴 CRITICAL: No auth token. User is not logged in.');
      return Stream.value(const AgentErrorEvent('Authentication required.'));
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
      'current_scan_id': currentScanId ?? '', // Pass real UUID or empty string
      'session_id': sessionId ?? '',
      'execution_step': step,
      'multimodal_metadata': {},
    };

    final rawStream = SSEClient.subscribeToSSE(
      method: SSERequestType.POST,
      url: '${ApiConstants.baseUrl}/agent/chat',
      header: {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: payload,
    );

    return rawStream.map((sseEvent) {
      final rawData = sseEvent.data;

      // Guard: detect HTML error pages (e.g. Cloudflare 1001, 502, 503).
      // If the server returns HTML instead of SSE, every line of HTML becomes
      // a separate "event" — causing an infinite retry loop. Terminate early.
      if (rawData != null && (rawData.trimLeft().startsWith('<') ||
          rawData.contains('<!DOCTYPE') ||
          rawData.contains('<html'))) {
        debugPrint('[ChatService] 🔴 Received HTML instead of SSE — backend may be down.');
        closeStream();
        return const AgentErrorEvent(
          'The AI server is temporarily unreachable. Please try again in a moment.',
        );
      }

      // Handle keepalive or empty events
      if (rawData == null || rawData.isEmpty || rawData.trim() == 'keepalive') {
        return const AgentKeepAliveEvent();
      }

      try {
        final json = jsonDecode(rawData) as Map<String, dynamic>;
        final type = json['type'] as String? ?? '';

        switch (type) {
          case 'text_token':
            return AgentTextEvent(json['content'] as String? ?? '');

          case 'tool_call':
            return AgentToolCallEvent(
              toolName: json['tool_name'] as String? ?? 'unknown_tool',
              input: (json['input'] as Map<String, dynamic>?) ?? {},
            );

          case 'ui_trigger':
            return AgentUiTriggerEvent(
              action: json['action'] as String? ?? '',
              payload: (json['payload'] as Map<String, dynamic>?) ?? {},
            );

          case 'citations':
            // Store citations until the done event aggregates them
            final sources = json['sources'] as List<dynamic>? ?? [];
            _pendingCitations
              ..clear()
              ..addAll(sources.map((s) => Citation.fromJson(s as Map<String, dynamic>)));
            return const AgentKeepAliveEvent(); // No UI update yet

          case 'done':
            final citations = List<Citation>.from(_pendingCitations);
            _pendingCitations.clear();
            return AgentDoneEvent(
              sessionId: json['session_id'] as String? ?? '',
              citations: citations,
            );

          case 'error':
            return AgentErrorEvent(json['message'] as String? ?? 'Unknown error from agent.');

          default:
            debugPrint('[ChatService] Unhandled SSE type: $type — data: $rawData');
            return const AgentKeepAliveEvent();
        }
      } catch (e) {
        debugPrint('[ChatService] ❌ Failed to parse SSE event: $rawData — Error: $e');
        return const AgentKeepAliveEvent(); // Swallow parse errors silently — don't retry
      }
    }).distinct(); // Deduplicate consecutive identical events (e.g. repeated error lines)
  }

  /// Call when the user leaves the chat screen or the agent finishes.
  void closeStream() {
    SSEClient.unsubscribeFromSSE();
    _pendingCitations.clear();
    debugPrint('🛑 Chat SSE Stream Closed.');
  }

  Stream<SSEModel> startAgentChatStream(String question, String patientId, String? currentScanId) async* {
    debugPrint('💬 Starting SSE connection (manual http to avoid retries)...');
    _pendingCitations.clear();

    final session = Supabase.instance.client.auth.currentSession;
    final token = session?.accessToken;

    if (token == null || token.isEmpty) {
      debugPrint('🔴 CRITICAL: No auth token. User is not logged in.');
      return;
    }

    String step = '';
    final qLower = question.toLowerCase();
    
    // Always map the execution step based on the prompt so the backend knows what to do
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
      'session_id': '',
      'execution_step': step,
      'multimodal_metadata': token == 'dev-bypass' ? {
        "cxr_image_url": "https://example.com/sample_cxr.jpg",
        "ecg_data_url": "https://example.com/sample_ecg.json",
        "skin_image_url": "https://example.com/sample_skin.jpg",
        "baseline_scan_id": "scan-001"
      } : {},
    };

    final request = http.Request('POST', Uri.parse('${ApiConstants.baseUrl}/agent/chat'))
      ..headers['Authorization'] = 'Bearer $token'
      ..headers['Content-Type'] = 'application/json'
      ..headers['Accept'] = 'text/event-stream'
      ..body = jsonEncode(payload);

    final client = http.Client();
    http.StreamedResponse response;

    try {
      response = await client.send(request);
      if (response.statusCode != 200) {
        debugPrint('[ChatService] 🔴 Backend returned ${response.statusCode}');
        client.close();
        throw Exception('Backend returned ${response.statusCode}. The server might be offline.');
      }
    } catch (e) {
      debugPrint('[ChatService] 🔴 Connection failed: $e');
      client.close();
      throw Exception('Connection failed: $e');
    }

    String currentEvent = '';
    String currentData = '';

    await for (final chunk in response.stream.transform(utf8.decoder).transform(const LineSplitter())) {
      if (chunk.startsWith('event: ')) {
        currentEvent = chunk.substring(7);
      } else if (chunk.startsWith('data: ')) {
        currentData = chunk.substring(6);
      } else if (chunk.isEmpty) {
        if (currentEvent.isNotEmpty) {
          yield SSEModel(id: '', event: currentEvent, data: currentData);
          currentEvent = '';
          currentData = '';
        }
      }
    }

    client.close();
  }
}