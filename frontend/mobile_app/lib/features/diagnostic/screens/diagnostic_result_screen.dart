// lib/features/diagnostic/screens/diagnostic_result_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

// =========================================================================
// MOCK DATA MODELS & DYNAMIC PROVIDER
// =========================================================================

class AIFinding {
  final String region;
  final String observation;
  final String riskLevel;
  final double confidence;

  AIFinding({
    required this.region,
    required this.observation,
    required this.riskLevel,
    required this.confidence,
  });
}

class DiagnosticResult {
  final String scanType;
  final String aiModel;
  final String method;
  final double overallConfidence;
  final bool isRedAlert;
  final List<String> tags;
  final String recommendation;
  final List<AIFinding> findings;

  DiagnosticResult({
    required this.scanType,
    required this.aiModel,
    required this.method,
    required this.overallConfidence,
    required this.isRedAlert,
    required this.tags,
    required this.recommendation,
    required this.findings,
  });
}

// THE UPGRADE: A Family Provider that returns data based on the requested module
final diagnosticResultProvider = Provider.family<DiagnosticResult, String>((ref, moduleName) {

  if (moduleName == 'ECG') {
    return DiagnosticResult(
      scanType: 'ECG',
      aiModel: 'CardioNet-V2',
      method: 'Rhythm & ST Segment Analysis',
      overallConfidence: 0.98,
      isRedAlert: false,
      tags: ['Sinus Rhythm', 'Normal Axis'],
      recommendation: 'Evidence-based protocol: Patient is stable. No acute ischemic changes detected. Routine follow-up.',
      findings: [
        AIFinding(region: 'QRS Complex', observation: 'Normal duration (80ms)', riskLevel: 'Normal', confidence: 0.99),
        AIFinding(region: 'ST Segment', observation: 'Isoelectric, no elevation', riskLevel: 'Normal', confidence: 0.98),
        AIFinding(region: 'T Wave', observation: 'Upright, normal morphology', riskLevel: 'Normal', confidence: 0.96),
      ],
    );
  }

  if (moduleName == 'Skin') {
    return DiagnosticResult(
      scanType: 'Skin',
      aiModel: 'DermoDetect-Pro',
      method: 'Dermoscopic Analysis',
      overallConfidence: 0.88,
      isRedAlert: true,
      tags: ['Asymmetry', 'Border Irregularity'],
      recommendation: 'Evidence-based protocol: Suspicious lesion detected. Immediate referral for biopsy recommended.',
      findings: [
        AIFinding(region: 'Pigmentation', observation: 'Asymmetrical distribution', riskLevel: 'High', confidence: 0.91),
        AIFinding(region: 'Border', observation: 'Notched and irregular', riskLevel: 'Moderate', confidence: 0.85),
        AIFinding(region: 'Color', observation: 'Multiple shades present', riskLevel: 'High', confidence: 0.89),
      ],
    );
  }

  // Default Fallback: Chest X-Ray
  return DiagnosticResult(
    scanType: 'Chest X-Ray',
    aiModel: 'DenseNet-121',
    method: 'Grad-CAM++',
    overallConfidence: 0.942,
    isRedAlert: true,
    tags: ['GGO', 'PE'],
    recommendation: 'Evidence-based protocol: Urgent pulmonology consult recommended. Initiate supportive oxygen therapy.',
    findings: [
      AIFinding(region: 'Left Lower Lobe', observation: 'Ground-glass opacity', riskLevel: 'High', confidence: 0.942),
      AIFinding(region: 'Right Middle Lobe', observation: 'Pleural effusion', riskLevel: 'Moderate', confidence: 0.875),
      AIFinding(region: 'Cardiac Silhouette', observation: 'Normal borders', riskLevel: 'Normal', confidence: 0.981),
    ],
  );
});

// =========================================================================
// SCREEN UI
// =========================================================================

const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);
const Color alertRed = Color(0xFFE63946);
const Color alertOrange = Color(0xFFF2994A);
const Color alertGreen = Color(0xFF00A36C);

class DiagnosticResultScreen extends ConsumerWidget {
  final String activeModule;

  const DiagnosticResultScreen({Key? key, required this.activeModule}) : super(key: key);

  @override
  Widget build(BuildContext context, WidgetRef ref) {

    final resultData = ref.watch(diagnosticResultProvider(activeModule));

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
                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 24.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _buildHeader(resultData.method),
                        const SizedBox(height: 24),

                        _buildModuleToggle(activeModule),
                        const SizedBox(height: 24),

                        _buildHeatmapCard(resultData),
                        const SizedBox(height: 32),

                        _buildAIFindingsHeader(resultData.isRedAlert),
                        const SizedBox(height: 16),
                        _buildAIFindingsList(resultData.findings),
                        const SizedBox(height: 24),

                        _buildRecommendationCard(resultData.recommendation),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: _buildBottomNav(context),
    );
  }

  // =========================================================================
  // UI WIDGET COMPONENTS
  // =========================================================================

  Widget _buildHeader(String method) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Diagnostic Result',
                style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: primaryBlue),
              ),
              const SizedBox(height: 4),
              Text(
                '$method analysis',
                style: const TextStyle(fontSize: 13, color: textLight),
              ),
            ],
          ),
        ),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: const Color(0xFFE6F7F0),
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: const Color(0xFFB3E6D0)),
          ),
          child: Row(
            children: const [
              Icon(Icons.wifi, size: 12, color: alertGreen),
              SizedBox(width: 4),
              Text('Offline', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: alertGreen)),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildModuleToggle(String activeScanType) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(30),
        boxShadow: [
          BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 5)),
        ],
      ),
      child: Row(
        children: [
          _buildTabItem('Chest X-Ray', isActive: activeScanType == 'Chest X-Ray'),
          _buildTabItem('ECG', isActive: activeScanType == 'ECG'),
          _buildTabItem('Skin', isActive: activeScanType == 'Skin'),
        ],
      ),
    );
  }

  Widget _buildTabItem(String title, {required bool isActive}) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          color: isActive ? primaryBlue : Colors.transparent,
          borderRadius: BorderRadius.circular(26),
        ),
        child: Center(
          child: Text(
            title,
            style: TextStyle(
              color: isActive ? Colors.white : textLight,
              fontWeight: isActive ? FontWeight.bold : FontWeight.w500,
              fontSize: 14,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeatmapCard(DiagnosticResult result) {
    IconData cardIcon = Icons.masks_outlined;
    if (result.scanType == 'ECG') cardIcon = Icons.show_chart_rounded;
    if (result.scanType == 'Skin') cardIcon = Icons.center_focus_weak_rounded;

    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(color: primaryBlue.withOpacity(0.15), blurRadius: 20, offset: const Offset(0, 10)),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: Column(
          children: [
            Stack(
              children: [
                Container(
                  height: 200,
                  width: double.infinity,
                  decoration: const BoxDecoration(
                    gradient: LinearGradient(
                      colors: [Color(0xFF2C3E50), Color(0xFF000000)],
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                    ),
                  ),
                  child: Center(
                    child: Icon(cardIcon, size: 100, color: Colors.white10),
                  ),
                ),

                if (result.isRedAlert) ...[
                  Positioned(
                    top: 50, left: 60,
                    child: Container(
                      width: 60, height: 60,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: accentCyan.withOpacity(0.4),
                        boxShadow: [BoxShadow(color: accentCyan.withOpacity(0.6), blurRadius: 25, spreadRadius: 10)],
                      ),
                    ),
                  ),
                  Positioned(
                    bottom: 30, right: 50,
                    child: Container(
                      width: 50, height: 50,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: alertRed.withOpacity(0.4),
                        boxShadow: [BoxShadow(color: alertRed.withOpacity(0.6), blurRadius: 25, spreadRadius: 10)],
                      ),
                    ),
                  ),
                ],

                Positioned(
                  top: 16,
                  left: 16,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: result.tags.asMap().entries.map((entry) {
                      int index = entry.key;
                      String tag = entry.value;
                      Color dotColor = index % 2 == 0 ? accentCyan : alertRed;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 8.0),
                        child: _buildOverlayTag(tag, dotColor),
                      );
                    }).toList(),
                  ),
                ),

                if (result.isRedAlert)
                  Positioned(
                    top: 16,
                    right: 16,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: alertRed,
                        borderRadius: BorderRadius.circular(8),
                        boxShadow: [BoxShadow(color: alertRed.withOpacity(0.4), blurRadius: 8, offset: const Offset(0, 4))],
                      ),
                      child: Row(
                        children: const [
                          Icon(Icons.warning_rounded, color: Colors.white, size: 14),
                          SizedBox(width: 4),
                          Text('RED ALERT', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 11, letterSpacing: 0.5)),
                        ],
                      ),
                    ),
                  )
                else
                  Positioned(
                    top: 16,
                    right: 16,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: alertGreen,
                        borderRadius: BorderRadius.circular(8),
                        boxShadow: [BoxShadow(color: alertGreen.withOpacity(0.4), blurRadius: 8, offset: const Offset(0, 4))],
                      ),
                      child: Row(
                        children: const [
                          Icon(Icons.check_circle_rounded, color: Colors.white, size: 14),
                          SizedBox(width: 4),
                          Text('NORMAL', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 11, letterSpacing: 0.5)),
                        ],
                      ),
                    ),
                  ),
              ],
            ),

            Container(
              color: const Color(0xFF1A2634),
              padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 20),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _buildStatColumn('Model', result.aiModel, Colors.white),
                  _buildStatColumn('Method', result.method.split(' ')[0], Colors.white),
                  _buildStatColumn('Confidence', '${(result.overallConfidence * 100).toStringAsFixed(1)}%', accentCyan),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildOverlayTag(String text, Color dotColor) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.6),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white24),
      ),
      child: Row(
        children: [
          Container(width: 8, height: 8, decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(text, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12)),
        ],
      ),
    );
  }

  Widget _buildStatColumn(String label, String value, Color valueColor) {
    return Column(
      children: [
        Text(label, style: const TextStyle(color: Colors.white54, fontSize: 11)),
        const SizedBox(height: 4),
        Text(value, style: TextStyle(color: valueColor, fontWeight: FontWeight.bold, fontSize: 14)),
      ],
    );
  }

  Widget _buildAIFindingsHeader(bool isRedAlert) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        const Text(
          'AI Findings',
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue),
        ),
        if (isRedAlert)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: const Color(0xFFFFEAEA),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Row(
              children: const [
                Icon(Icons.error_outline, size: 14, color: alertRed),
                SizedBox(width: 4),
                Text('Urgent Review', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: alertRed)),
              ],
            ),
          ),
      ],
    );
  }

  Widget _buildAIFindingsList(List<AIFinding> findings) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: [
          BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 15, offset: const Offset(0, 5)),
        ],
      ),
      child: Column(
        children: findings.asMap().entries.map((entry) {
          int index = entry.key;
          AIFinding finding = entry.value;

          Color statusColor = alertGreen;
          if (finding.riskLevel == 'High') statusColor = alertRed;
          if (finding.riskLevel == 'Moderate') statusColor = alertOrange;

          return Column(
            children: [
              _buildFindingRow(
                  finding.region,
                  finding.observation,
                  finding.riskLevel,
                  finding.confidence,
                  statusColor
              ),
              if (index < findings.length - 1)
                const Divider(height: 1, thickness: 1, color: Color(0xFFF0F4F8)),
            ],
          );
        }).toList(),
      ),
    );
  }

  Widget _buildFindingRow(String title, String subtitle, String status, double percent, Color color) {
    return IntrinsicHeight(
      child: Row(
        children: [
          Container(width: 4, color: color),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15, color: textDark)),
                        const SizedBox(height: 4),
                        Text(subtitle, style: const TextStyle(fontSize: 13, color: textLight)),
                      ],
                    ),
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(status, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: color)),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Container(
                            width: 50,
                            height: 4,
                            decoration: BoxDecoration(color: color.withOpacity(0.2), borderRadius: BorderRadius.circular(2)),
                            child: Align(
                              alignment: Alignment.centerLeft,
                              child: Container(
                                width: 50 * percent,
                                height: 4,
                                decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(2)),
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Text('${(percent * 100).toStringAsFixed(1)}%', style: const TextStyle(fontSize: 12, color: textLight)),
                        ],
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRecommendationCard(String recommendationText) {
    List<String> parts = recommendationText.split(': ');
    String title = parts.isNotEmpty ? parts[0] : 'AI Recommendation';
    String subtitle = parts.length > 1 ? parts[1] : recommendationText;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFEAF8FC),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: accentCyan.withOpacity(0.2),
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Icon(Icons.psychology, color: accentCyan, size: 28),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: primaryBlue)),
                const SizedBox(height: 4),
                Text(subtitle, style: const TextStyle(fontSize: 13, color: textLight)),
              ],
            ),
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
        currentIndex: 1,
        selectedLabelStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
        unselectedLabelStyle: const TextStyle(fontSize: 12),
        onTap: (index) {
          if (index == 0) context.goNamed('dashboard');
          if (index == 1) return;
          if (index == 2) context.goNamed('ai_chat');
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