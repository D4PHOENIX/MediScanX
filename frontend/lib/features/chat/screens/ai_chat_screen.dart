// lib/features/chat/screens/ai_chat_screen.dart
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../models/chat_models.dart';
import '../providers/chat_provider.dart';
import 'package:mediscanx_mobile/features/diagnostic/models/diagnostic_result.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

// Shared Colors
const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);

// Message Bubble Colors
const Color aiBubbleBg = Colors.white;
const Color userBubbleBg = Color(0xFF005C7A);

class AIChatScreen extends ConsumerStatefulWidget {
  final DiagnosticResult? preloadedResult;
  final String? scanContextId;
  final String? initialPrompt;

  const AIChatScreen({
    Key? key,
    this.preloadedResult,
    this.scanContextId,
    this.initialPrompt,
  }) : super(key: key);

  @override
  ConsumerState<AIChatScreen> createState() => _AIChatScreenState();
}

class _AIChatScreenState extends ConsumerState<AIChatScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();

    if (widget.scanContextId != null && widget.initialPrompt != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        ref.read(chatProvider.notifier).createNewSession();
        ref.read(chatProvider.notifier).setScanContext(widget.scanContextId!);
        _handleSubmitted(widget.initialPrompt!);
      });
    } else if (widget.preloadedResult != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        ref.read(chatProvider.notifier).createNewSession();
        final result = widget.preloadedResult!;
        ref.read(chatProvider.notifier).setScanContext(result.id);

        final findingsStr = result.findings.map((f) => "${f.region} (${f.riskLevel} risk)").join(", ");

        final autoPrompt = "I just completed a ${result.scanType} scan. "
            "The system detected the following: ${result.tags.join(', ')} with a confidence of ${(result.overallConfidence * 100).toStringAsFixed(1)}%. "
            "Specific findings include: $findingsStr. "
            "The automated recommendation is: '${result.recommendation}'.\n\n"
            "Can you explain what these results mean in simple terms and advise me on my next steps?";

        _handleSubmitted(autoPrompt);
      });
    }
  }

  void _handleSubmitted(String text) {
    if (text.trim().isEmpty) return;
    _textController.clear();

    final notifier = ref.read(chatProvider.notifier);
    notifier.addUserMessage(text);
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  void dispose() {
    _textController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final role = (Supabase.instance.client.auth.currentUser?.userMetadata?['role'] ??
        Supabase.instance.client.auth.currentUser?.userMetadata?['userType'])
        ?.toString()
        .toLowerCase();
    final bool isDoctor = role == 'doctor';

    final messages = ref.watch(chatProvider);
    final isStreaming = ref.watch(chatProvider.notifier).isStreaming;
    final agentAction = ref.watch(chatProvider.notifier).agentAction;

    ref.listen<List<ChatMessage>>(chatProvider, (previous, next) {
      _scrollToBottom();
    });

    return Scaffold(
      backgroundColor: bgLight,
      body: Stack(
        children: [
          Positioned(
            top: 150,
            right: -80,
            child: Opacity(
              opacity: 0.04,
              child: Image.asset(
                'assets/images/lungs_watermark.png',
                width: 400,
                errorBuilder: (context, error, stackTrace) => const Icon(Icons.masks_outlined, size: 400, color: primaryBlue),
              ),
            ),
          ),
          SafeArea(
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
                  child: _buildHeader(),
                ),
                Expanded(
                  child: SingleChildScrollView(
                    controller: _scrollController,
                    padding: const EdgeInsets.symmetric(horizontal: 24.0),
                    child: Column(
                      children: [
                        _buildPoweredByBanner(),
                        const SizedBox(height: 16),
                        ...messages.asMap().entries.map((entry) => _buildMessageBubble(entry.value, entry.key, messages)).toList(),
                        if (isStreaming && agentAction.isNotEmpty)
                          _buildAgentActionIndicator(agentAction),
                        const SizedBox(height: 16),
                        if (!isStreaming) _buildSuggestionChips(),
                        const SizedBox(height: 24),
                      ],
                    ),
                  ),
                ),
                _buildInputArea(isStreaming),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: _buildBottomNav(context, isDoctor),
    );
  }

  Widget _buildHeader() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
          GestureDetector(
            behavior: HitTestBehavior.opaque,
              onTap: () {
                if (context.canPop()) {
                  context.pop();
                } else {
                  context.goNamed('dashboard');
                }
              },
            child: Container(
              margin: const EdgeInsets.only(right: 12, top: 2),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.08), blurRadius: 8, offset: const Offset(0, 2))],
              ),
              child: const Icon(Icons.arrow_back_ios_new_rounded, size: 16, color: primaryBlue),
            ),
          ),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: const [
              Text('RAG Medical AI', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: primaryBlue)),
              SizedBox(height: 4),
              Text(
                'Evidence-based clinical support',
                style: TextStyle(fontSize: 13, color: textLight),
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0xFFE6F7F0),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: const Color(0xFFB3E6D0)),
              ),
              child: Row(
                children: const [
                  Icon(Icons.wifi, size: 12, color: Color(0xFF00A36C)),
                  SizedBox(width: 4),
                  Text('Cloud Active', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF00A36C))),
                ],
              ),
            ),
            const SizedBox(height: 12),
            GestureDetector(
              onTap: () {
                final patientId = Supabase.instance.client.auth.currentUser?.id ?? '';
                final activeScanId = widget.scanContextId ?? widget.preloadedResult?.id;
                if (activeScanId != null) {
                  context.pushNamed('referral', extra: {
                    'patientId': patientId,
                    'scanIds': [activeScanId],
                  });
                } else {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('No active scan selected for referral.')),
                  );
                }
              },
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [accentCyan, Color(0xFF008BA6)],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(20),
                  boxShadow: [
                    BoxShadow(
                      color: accentCyan.withOpacity(0.3),
                      blurRadius: 8,
                      offset: const Offset(0, 3),
                    )
                  ],
                ),
                child: Row(
                  children: const [
                    Icon(Icons.send_rounded, size: 14, color: Colors.white),
                    SizedBox(width: 6),
                    Text('Share Report', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.white)),
                  ],
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildPoweredByBanner() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 5))],
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: accentCyan.withOpacity(0.2),
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Icon(Icons.search, color: accentCyan, size: 28),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: const [
                Text(
                  'Powered by PubMed · WHO · Clinical Guidelines RAG',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: textDark),
                ),
                SizedBox(height: 4),
                Text(
                  'Query top-tier medical databases and guidelines for real-time support.',
                  style: TextStyle(fontSize: 12, color: textLight),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageBubble(ChatMessage message, int index, List<ChatMessage> allMessages) {
    bool isStreamingBubble = message.id.startsWith('streaming_');
    bool hasError = !message.isUser && message.text.contains('❌');
    
    return Column(
      children: [
        Row(
          mainAxisAlignment: message.isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!message.isUser) ...[
              Container(
                margin: const EdgeInsets.only(top: 8),
                padding: const EdgeInsets.all(6),
                decoration: const BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                  boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 4, offset: Offset(0, 2))],
                ),
                child: Icon(hasError ? Icons.error_outline : (isStreamingBubble ? Icons.auto_awesome : Icons.psychology), color: hasError ? Colors.red : accentCyan, size: 18),
              ),
              const SizedBox(width: 12),
            ],
            Flexible(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: BoxDecoration(
                  color: message.isUser ? userBubbleBg : (hasError ? Colors.red.shade50 : aiBubbleBg),
                  borderRadius: BorderRadius.circular(20).copyWith(
                    bottomLeft: message.isUser ? const Radius.circular(20) : const Radius.circular(0),
                    bottomRight: message.isUser ? const Radius.circular(0) : const Radius.circular(20),
                  ),
                  boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 10, offset: const Offset(0, 5))],
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    message.isUser
                        ? Text(
                            message.text,
                            style: const TextStyle(color: Colors.white, fontSize: 14, height: 1.4),
                          )
                        : MarkdownBody(
                            data: message.text,
                            styleSheet: MarkdownStyleSheet(
                              p: const TextStyle(color: textDark, fontSize: 14, height: 1.4),
                              listBullet: const TextStyle(color: textDark, fontSize: 14, height: 1.4),
                            ),
                          ),
                    if (hasError) ...[
                      const SizedBox(height: 12),
                      Align(
                        alignment: Alignment.centerRight,
                        child: OutlinedButton.icon(
                          onPressed: () {
                             if (index > 0) {
                               final prevMsg = allMessages[index - 1];
                               if (prevMsg.isUser) {
                                 ref.read(chatProvider.notifier).retryMessage(prevMsg.text);
                               }
                             }
                          },
                          icon: const Icon(Icons.refresh, size: 16, color: Colors.red),
                          label: const Text('Retry', style: TextStyle(color: Colors.red)),
                          style: OutlinedButton.styleFrom(
                            side: const BorderSide(color: Colors.red),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                          ),
                        ),
                      )
                    ],
                    if (!message.isUser && message.citations != null && message.citations!.where((c) => c.sourceId != 'Unknown Source' && c.relevanceScore > 0).isNotEmpty) ...[
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 8.0),
                        child: Divider(height: 1, thickness: 0.5, color: Color(0xFFECEFF1)),
                      ),
                      ...message.citations!.where((c) => c.sourceId != 'Unknown Source' && c.relevanceScore > 0).map((citation) => Padding(
                        padding: const EdgeInsets.only(bottom: 6.0),
                        child: InkWell(
                          onTap: () {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text('${citation.sourceId}: "${citation.snippet}"'),
                                duration: const Duration(seconds: 4),
                                backgroundColor: primaryBlue,
                              ),
                            );
                          },
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(Icons.menu_book_rounded, size: 11, color: accentCyan),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Text(
                                  '${citation.sourceId} (Relevance: ${(citation.relevanceScore * 100).toStringAsFixed(0)}%)',
                                  style: const TextStyle(color: accentCyan, fontSize: 11, fontWeight: FontWeight.bold, decoration: TextDecoration.underline),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            ],
                          ),
                        ),
                      )).toList(),
                    ]
                  ],
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
      ],
    );
  }

  Widget _buildAgentActionIndicator(String actionText) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16.0),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(6),
            decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle),
            child: const Icon(Icons.settings_suggest, color: textLight, size: 18),
          ),
          const SizedBox(width: 12),
          Flexible(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(20).copyWith(bottomLeft: Radius.zero),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.max,
                children: [
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2, color: accentCyan),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      actionText,
                      style: const TextStyle(color: textLight, fontSize: 12, fontStyle: FontStyle.italic),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSuggestionChips() {
    final List<String> suggestions = [
      "Differential for bilateral GGOs",
      "Dexamethasone dosing",
      "Referral criteria"
    ];

    return Wrap(
      spacing: 12,
      runSpacing: 8,
      children: suggestions.map((suggestion) {
        return GestureDetector(
          onTap: () => _handleSubmitted(suggestion),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(20),
              boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 5, offset: const Offset(0, 2))],
              border: Border.all(color: Colors.black12),
            ),
            child: Text(suggestion, style: const TextStyle(fontSize: 12, color: textLight)),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildInputArea(bool isStreaming) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, -5))],
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _textController,
              onSubmitted: _handleSubmitted,
              enabled: !isStreaming,
              decoration: InputDecoration(
                hintText: isStreaming ? 'AI is thinking...' : 'Ask about symptoms, protocols...',
                hintStyle: const TextStyle(color: textLight, fontSize: 14),
                border: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(vertical: 12),
              ),
              style: const TextStyle(color: textDark, fontSize: 14),
            ),
          ),
          const SizedBox(width: 16),
          IconButton(
            icon: Icon(isStreaming ? Icons.stop_circle_outlined : Icons.send_rounded, color: isStreaming ? Colors.red : accentCyan),
            onPressed: () {
              if (isStreaming) {
                ref.read(chatProvider.notifier).stopStream();
              } else {
                _handleSubmitted(_textController.text);
              }
            },
          ),
        ],
      ),
    );
  }

  Widget _buildBottomNav(BuildContext context, bool isDoctor) {
    return Container(
      decoration: BoxDecoration(
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, -5))],
      ),
      child: BottomNavigationBar(
        type: BottomNavigationBarType.fixed,
        backgroundColor: Colors.white,
        selectedItemColor: accentCyan,
        unselectedItemColor: textLight,
        currentIndex: isDoctor ? 3 : 2,
        selectedLabelStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
        unselectedLabelStyle: const TextStyle(fontSize: 12),
        onTap: (index) {
          if (index == 0) context.goNamed('dashboard');
          if (index == 1) context.goNamed('diagnostic');
          if (isDoctor) {
            if (index == 2) context.goNamed('triage');
            if (index == 3) return;
          } else {
            if (index == 2) return;
          }
        },
        items: isDoctor
            ? const [
          BottomNavigationBarItem(icon: Icon(Icons.dashboard_rounded), label: 'Dashboard'),
          BottomNavigationBarItem(icon: Icon(Icons.analytics_rounded), label: 'Diagnostic'),
          BottomNavigationBarItem(icon: Icon(Icons.priority_high), label: 'Triage'),
          BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'AI Chat'),
        ]
            : const [
          BottomNavigationBarItem(icon: Icon(Icons.dashboard_rounded), label: 'Dashboard'),
          BottomNavigationBarItem(icon: Icon(Icons.analytics_rounded), label: 'Diagnostic'),
          BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'AI Chat'),
        ],
      ),
    );
  }
}