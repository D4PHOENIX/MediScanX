// lib/features/chat/screens/ai_chat_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

// Shared Colors (Defined in-file for independence, use constants file later)
const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);

// Message Bubble Colors
const Color aiBubbleBg = Colors.white;
const Color userBubbleBg = Color(0xFF005C7A); // Deep Teal-Blue from image

// Simple Message Model to store chat state
class ChatMessage {
  final String text;
  final bool isUser;
  final String? source; // "PubMed", "WHO", etc.

  ChatMessage({required this.text, required this.isUser, this.source});
}

class AIChatScreen extends ConsumerStatefulWidget {
  const AIChatScreen({Key? key}) : super(key: key);

  @override
  ConsumerState<AIChatScreen> createState() => _AIChatScreenState();
}

class _AIChatScreenState extends ConsumerState<AIChatScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  // Local screen state for the message list
  List<ChatMessage> _messages = [
    // Pre-populate with the initial message from image_12.png
    ChatMessage(
      text: "Hello, I'm MediScanX AI — your evidence-based clinical decision support assistant. I can help analyze findings, suggest differential diagnoses, and provide treatment protocols referenced to WHO and PubMed guidelines.",
      isUser: false,
    ),
  ];

  void _handleSubmitted(String text) {
    if (text.trim().isEmpty) return;
    _textController.clear();
    setState(() {
      _messages.add(ChatMessage(text: text, isUser: true));
    });
    // Add a simple mock AI response for now
    Future.delayed(const Duration(seconds: 1), () {
      setState(() {
        _messages.add(ChatMessage(text: "Reviewing symptoms. This could be consistent with GGO patterns. Let's look up PubMed protocols...", isUser: false, source: "PubMed"));
      });
      _scrollToBottom();
    });
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: bgLight,
      body: Stack(
        children: [
          // ==========================================
          // 1. STATIC WATERMARK BACKGROUND
          // ==========================================
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

          // ==========================================
          // 2. FOREGROUND CONTENT
          // ==========================================
          SafeArea(
            child: Column(
              children: [
                // Fixed Header Area
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
                  child: _buildHeader(),
                ),

                // Scrollable Chat Message Area
                Expanded(
                  child: SingleChildScrollView(
                    controller: _scrollController,
                    padding: const EdgeInsets.symmetric(horizontal: 24.0),
                    child: Column(
                      children: [
                        _buildPoweredByBanner(),
                        const SizedBox(height: 16),
                        ..._messages.map(_buildMessageBubble).toList(),
                        const SizedBox(height: 16),
                        _buildSuggestionChips(),
                        const SizedBox(height: 24), // Extra bottom padding for messages
                      ],
                    ),
                  ),
                ),

                // Fixed Input Area
                _buildInputArea(),
              ],
            ),
          ),
        ],
      ),
      // Active navigation index is now set to 2 (Chat)
      bottomNavigationBar: _buildBottomNav(context),
    );
  }

  // =========================================================================
  // UI WIDGET COMPONENTS
  // =========================================================================

  Widget _buildHeader() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // FIX: Wrapped Column in Expanded to prevent RenderFlex overflow
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
        const SizedBox(width: 8), // Breathing room
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
              Text('Offline-First', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF00A36C))),
            ],
          ),
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
              children: [
                const Text(
                  'Powered by PubMed · WHO · Clinical Guidelines RAG',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: textDark),
                ),
                const SizedBox(height: 4),
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

  Widget _buildMessageBubble(ChatMessage message) {
    return Column(
      children: [
        Row(
          mainAxisAlignment: message.isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!message.isUser) ...[
              // AI Avatar
              Container(
                margin: const EdgeInsets.only(top: 8),
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: Colors.white, // In image it is white/transparent
                  shape: BoxShape.circle,
                  boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 4, offset: const Offset(0, 2))],
                ),
                child: const Icon(Icons.psychology, color: accentCyan, size: 18),
              ),
              const SizedBox(width: 12),
            ],
            Flexible(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: BoxDecoration(
                  color: message.isUser ? userBubbleBg : aiBubbleBg,
                  borderRadius: BorderRadius.circular(20).copyWith(
                    bottomLeft: message.isUser ? const Radius.circular(20) : const Radius.circular(0),
                    bottomRight: message.isUser ? const Radius.circular(0) : const Radius.circular(20),
                  ),
                  boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 10, offset: const Offset(0, 5))],
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      message.text,
                      style: TextStyle(color: message.isUser ? Colors.white : textDark, fontSize: 14),
                    ),
                    if (message.source != null) ...[
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          const Icon(Icons.cloud_queue, size: 11, color: accentCyan),
                          const SizedBox(width: 4),
                          Text(message.source!, style: const TextStyle(color: accentCyan, fontSize: 10, fontWeight: FontWeight.bold)),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16), // Space between messages
      ],
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

  Widget _buildInputArea() {
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
              decoration: const InputDecoration(
                hintText: 'Ask about symptoms, protocols...',
                hintStyle: TextStyle(color: textLight, fontSize: 14),
                border: InputBorder.none,
                contentPadding: EdgeInsets.symmetric(vertical: 12),
              ),
              style: const TextStyle(color: textDark, fontSize: 14),
            ),
          ),
          const SizedBox(width: 16),
          IconButton(
            icon: const Icon(Icons.send_rounded, color: accentCyan),
            onPressed: () => _handleSubmitted(_textController.text),
          ),
        ],
      ),
    );
  }

  Widget _buildBottomNav(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, -5))],
      ),
      child: BottomNavigationBar(
        type: BottomNavigationBarType.fixed,
        backgroundColor: Colors.white,
        selectedItemColor: accentCyan,
        unselectedItemColor: textLight,
        currentIndex: 2, // NEW: Active navigation is now index 2 (Chat)
        selectedLabelStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
        unselectedLabelStyle: const TextStyle(fontSize: 12),
        onTap: (index) {
          if (index == 0) context.goNamed('dashboard');
          if (index == 1) context.goNamed('diagnostic');
          if (index == 2) return;
          if (index == 3) context.goNamed('referral');
        },
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.dashboard_rounded), label: 'Dashboard'),
          BottomNavigationBarItem(icon: Icon(Icons.analytics_rounded), label: 'Diagnostic'),
          BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'AI Chat'),
          BottomNavigationBarItem(icon: Icon(Icons.qr_code_scanner), label: 'Referral'),
        ],
      ),
    );
  }
}