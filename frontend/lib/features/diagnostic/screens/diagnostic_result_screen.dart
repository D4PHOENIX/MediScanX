// lib/features/diagnostic/screens/diagnostic_result_screen.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'dart:convert';
import 'dart:typed_data';

// --- STRICT PACKAGE IMPORTS ---
import 'package:mediscanx_mobile/features/diagnostic/models/diagnostic_result.dart';
import 'package:mediscanx_mobile/core/database/database_manager.dart';
import 'package:mediscanx_mobile/features/diagnostic/services/scan_dao.dart';
import 'package:uuid/uuid.dart';
import 'package:mediscanx_mobile/core/widgets/authenticated_network_image.dart';
import 'package:mediscanx_mobile/core/utils/error_helper.dart'; // NEW IMPORT
import 'package:mediscanx_mobile/features/diagnostic/services/cloud_diagnostic_service.dart';
import 'dart:io';

// Fallback Provider for ECG and Skin mock data (used if no real ML data is passed)
final diagnosticResultProvider = Provider.family<DiagnosticResult, String>((ref, moduleName) {
  if (moduleName == 'ECG') {
    return DiagnosticResult(
      id: const Uuid().v4(),
      scanDate: DateTime.now(),
      imagePath: '',
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
      id: const Uuid().v4(),
      scanDate: DateTime.now(),
      imagePath: '',
      scanType: 'Skin Lesion',
      aiModel: 'CNN Vision Model',
      method: 'INT8 Quantized TFLite',
      overallConfidence: 0.92,
      isRedAlert: true,
      tags: ['Melanoma', 'Urgent'],
      recommendation: 'High risk of malignancy detected (Melanoma). Urgent dermatological biopsy recommended.',
      findings: [
        AIFinding(region: 'Melanoma', observation: 'Highest probability match', riskLevel: 'High', confidence: 0.92),
        AIFinding(region: 'Melanocytic Nevi', observation: 'Secondary differential', riskLevel: 'Low', confidence: 0.05),
        AIFinding(region: 'Benign Keratosis', observation: 'Low probability', riskLevel: 'Low', confidence: 0.02),
      ],
    );
  }

  return DiagnosticResult(
    id: const Uuid().v4(),
    scanDate: DateTime.now(),
    imagePath: '',
    scanType: 'Unknown',
    aiModel: 'Unknown',
    method: 'N/A',
    overallConfidence: 0.0,
    isRedAlert: false,
    tags: [],
    recommendation: 'No data available.',
    findings: [],
  );
});

const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);
const Color alertRed = Color(0xFFE63946);
const Color alertOrange = Color(0xFFF2994A);
const Color alertGreen = Color(0xFF00A36C);

// Removed legacy base64 decoding
class DiagnosticResultScreen extends ConsumerStatefulWidget {
  final String activeModule;
  final DiagnosticResult? offlineResult;

  const DiagnosticResultScreen({
    Key? key,
    required this.activeModule,
    this.offlineResult,
  }) : super(key: key);

  @override
  ConsumerState<DiagnosticResultScreen> createState() => _DiagnosticResultScreenState();
}

class _DiagnosticResultScreenState extends ConsumerState<DiagnosticResultScreen> {
  bool _showHeatmap = true;
  double _heatmapOpacity = 0.6;

  // 🔴 Force-saves to SQLite/Supabase dynamically on button press
  Future<void> _saveAndConsultAI(BuildContext context, DiagnosticResult result) async {
    final currentUserId = Supabase.instance.client.auth.currentUser?.id;
    if (currentUserId == null) return;

    // Use a simpler loading approach to avoid Navigator nesting crashes
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Saving and connecting to AI...'), duration: Duration(seconds: 2)),
    );

    try {
      final dao = ScanDao(DatabaseManager.drift);
      await dao.insertScan(result, currentUserId);

      // Pass the scan UUID so the AI agent can reference this specific scan
      if (context.mounted) {
        context.pushNamed('ai_chat', extra: result);
      }
    } catch (e) {
      debugPrint('Error saving record: $e');
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(ErrorHelper.getHumanReadableError(e))));
      }
    }
  }

  Future<void> _deleteScan(DiagnosticResult resultData) async {
    final bool? confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete Scan', style: TextStyle(color: primaryBlue, fontWeight: FontWeight.bold)),
        content: const Text(
            'Are you sure you want to delete this scan?\n\n'
            'Any reports already generated from it will remain.',
            style: TextStyle(color: textDark)),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel', style: TextStyle(color: textLight)),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: ElevatedButton.styleFrom(backgroundColor: alertRed),
            child: const Text('Delete', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Deleting scan...')),
    );

    try {
      // 1. Delete from Cloud
      final cloudService = CloudDiagnosticService();
      await cloudService.deleteScan(resultData.id);

      // 2. Delete from Local DB
      final dao = ScanDao(DatabaseManager.drift);
      await dao.db.customStatement('DELETE FROM scan_results WHERE id = ? OR scan_id = ?', [resultData.id, resultData.id]);
      
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Scan deleted successfully.')),
      );
      
      // Navigate back
      context.pop();
    } catch (e) {
      debugPrint('🔴 Delete failed: $e');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not delete scan. Please try again.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final role = (Supabase.instance.client.auth.currentUser?.userMetadata?['role'] ??
        Supabase.instance.client.auth.currentUser?.userMetadata?['userType'])
        ?.toString()
        .toLowerCase();
    final bool isDoctor = role == 'doctor';

    final DiagnosticResult resultData = widget.offlineResult != null
        ? widget.offlineResult!
        : ref.watch(diagnosticResultProvider(widget.activeModule));

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
                  padding: const EdgeInsets.only(left: 24.0, right: 24.0, top: 24.0, bottom: 8.0),
                  child: _buildHeader(resultData, context),
                ),
                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _buildModuleToggle(widget.activeModule),
                        const SizedBox(height: 24),

                        _buildHeatmapCard(resultData),
                        const SizedBox(height: 32),

                        _buildAIFindingsHeader(resultData.isRedAlert),
                        const SizedBox(height: 16),
                        _buildAIFindingsList(resultData.findings),
                        const SizedBox(height: 24),

                        _buildRecommendationCard(resultData.recommendation),
                        const SizedBox(height: 32),

                        // 🔴 NEW INTERACTION BUTTON: Save and Nav to Chat
                        SizedBox(
                          width: double.infinity,
                          height: 56,
                          child: ElevatedButton.icon(
                            onPressed: () => _saveAndConsultAI(context, resultData),
                            icon: const Icon(Icons.chat_bubble_outline_rounded, color: Colors.white),
                            label: const Text(
                              'Save & Discuss with AI',
                              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white),
                            ),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: primaryBlue,
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                              elevation: 2,
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        SizedBox(
                          width: double.infinity,
                          height: 56,
                          child: OutlinedButton.icon(
                            onPressed: () => _deleteScan(resultData),
                            icon: const Icon(Icons.delete_outline, color: alertRed),
                            label: const Text(
                              'Delete Scan',
                              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: alertRed),
                            ),
                            style: OutlinedButton.styleFrom(
                              side: const BorderSide(color: alertRed),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: _buildBottomNav(context, isDoctor),
    );
  }

  Widget _buildHeader(DiagnosticResult resultData, BuildContext context) {
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
            children: [
              const Text('Diagnostic Result', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: primaryBlue)),
              const SizedBox(height: 4),
              Text('${resultData.method} analysis', style: const TextStyle(fontSize: 13, color: textLight)),
            ],
          ),
        ),
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
                  Icon(Icons.wifi, size: 12, color: alertGreen),
                  SizedBox(width: 4),
                  Text('Offline-First', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: alertGreen)),
                ],
              ),
            ),
            const SizedBox(height: 12),
            GestureDetector(
              onTap: () {
                context.pushNamed('referral', extra: {
                  'patientId': Supabase.instance.client.auth.currentUser?.id ?? '',
                  'scanIds': [resultData.id],
                });
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
                    Icon(Icons.share, size: 14, color: Colors.white),
                    SizedBox(width: 6),
                    Text('Share', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.white)),
                  ],
                ),
              ),
            ),
          ],
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
        boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 5))],
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
    if (result.scanType.contains('ECG')) cardIcon = Icons.show_chart_rounded;
    if (result.scanType.contains('Skin')) cardIcon = Icons.center_focus_weak_rounded;

    final xai = result.xai;
    final bool hasGeneratedXai = xai?.status == 'generated' && xai?.url != null;
    final bool isOverlay = xai?.kind == 'heatmap_overlay';
    final bool isTrace = xai?.kind == 'reconstructed_trace';
    
    // Check if we can show a heatmap toggle
    final bool canShowHeatmap = hasGeneratedXai || isTrace;

    return Column(
      children: [
        Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(24),
            boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.15), blurRadius: 20, offset: const Offset(0, 10))],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(24),
            child: Column(
              children: [
                Stack(
                  children: [
                    Container(
                      height: 250,
                      width: double.infinity,
                      decoration: const BoxDecoration(
                        gradient: LinearGradient(
                          colors: [Color(0xFF2C3E50), Color(0xFF000000)],
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                        ),
                      ),
                      child: Stack(
                        fit: StackFit.expand,
                        children: [
                          // Base Layer
                          if (isTrace)
                            // If it's a trace, we DO NOT show original image. Just a dark background or the trace itself.
                            Center(child: Icon(cardIcon, size: 100, color: Colors.white10))
                          else if (result.imagePath.startsWith('http'))
                            AuthenticatedNetworkImage(imageUrl: result.imagePath, fit: BoxFit.contain)
                          else if (result.imagePath.isNotEmpty && File(result.imagePath).existsSync())
                            Image.file(File(result.imagePath), fit: BoxFit.contain)
                          else
                            Center(child: Icon(cardIcon, size: 100, color: Colors.white10)),
                          
                          // Heatmap Layer (if toggled on)
                          if (_showHeatmap && hasGeneratedXai)
                            Opacity(
                              opacity: isOverlay ? _heatmapOpacity : 1.0, // Trace is fully opaque
                              child: AuthenticatedNetworkImage(imageUrl: xai!.url!, fit: BoxFit.contain),
                            ),
                            
                          // Dark overlay for readability of tags
                          Container(color: Colors.black.withOpacity(0.1)),
                        ],
                      )
                    ),
                    
                    if (result.isRedAlert)
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
                    
                    // Tags
                    Positioned(
                      top: 16,
                      left: 16,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: result.tags.asMap().entries.map((entry) {
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 8.0),
                            child: _buildOverlayTag(entry.value, entry.key % 2 == 0 ? accentCyan : alertRed),
                          );
                        }).toList(),
                      ),
                    ),
                    
                    // Scan Status Badge
                    Positioned(
                      top: 16,
                      right: 16,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        decoration: BoxDecoration(
                          color: result.scanStatus == 2 || result.isRedAlert 
                                 ? alertRed 
                                 : result.scanStatus == 1 
                                     ? Colors.orange 
                                     : result.scanStatus == 0 
                                         ? alertGreen 
                                         : Colors.grey,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Row(
                          children: [
                            Icon(
                              result.scanStatus == 2 || result.isRedAlert 
                                 ? Icons.warning_rounded 
                                 : result.scanStatus == 1 
                                     ? Icons.info_outline 
                                     : result.scanStatus == 0 
                                         ? Icons.check_circle_rounded 
                                         : Icons.help_outline,
                              color: Colors.white, size: 14),
                            const SizedBox(width: 4),
                            Text(
                              result.scanStatus == 2 || result.isRedAlert 
                                 ? 'RED ALERT' 
                                 : result.scanStatus == 1 
                                     ? 'WARNING' 
                                     : result.scanStatus == 0 
                                         ? 'NORMAL' 
                                         : 'UNKNOWN',
                              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 11)
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
                
                // Trace Caption
                if (isTrace && _showHeatmap)
                  Container(
                    width: double.infinity,
                    color: Colors.black87,
                    padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
                    child: const Text(
                      'Reconstructed Lead I signal — not your original scan.',
                      style: TextStyle(color: Colors.white70, fontSize: 12, fontStyle: FontStyle.italic),
                      textAlign: TextAlign.center,
                    ),
                  ),

                // Skipped Edge Banner
                if (xai?.status == 'skipped_edge')
                  Container(
                    width: double.infinity,
                    color: const Color(0xFFFFF4E5),
                    padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 16),
                    child: Row(
                      children: const [
                        Icon(Icons.info_outline, color: alertOrange, size: 18),
                        SizedBox(width: 8),
                        Expanded(child: Text('Heatmaps are not available for on-device scans.', style: TextStyle(color: Color(0xFFB86C00), fontSize: 12))),
                      ],
                    ),
                  ),

                // Failed XAI Banner
                if (xai?.status == 'failed')
                  Container(
                    width: double.infinity,
                    color: const Color(0xFFFFEAEA),
                    padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 16),
                    child: Row(
                      children: const [
                        Icon(Icons.error_outline, color: alertRed, size: 18),
                        SizedBox(width: 8),
                        Expanded(child: Text('Heatmap generation failed.', style: TextStyle(color: alertRed, fontSize: 12))),
                      ],
                    ),
                  ),

                // None XAI Banner
                if (xai?.status == 'none')
                  Container(
                    width: double.infinity,
                    color: const Color(0xFFF3F4F6),
                    padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 16),
                    child: Row(
                      children: const [
                        Icon(Icons.info_outline, color: Colors.black54, size: 18),
                        SizedBox(width: 8),
                        Expanded(child: Text('Explainability heatmap is not available for this scan.', style: TextStyle(color: Colors.black87, fontSize: 12))),
                      ],
                    ),
                  ),

                Container(
                  color: const Color(0xFF1A2634),
                  padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 20),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      _buildStatColumn('Model', result.aiModel, Colors.white),
                      _buildStatColumn('Method', result.method.split(' ')[0], Colors.white),
                      _buildStatColumn(
                        'Confidence', 
                        result.overallConfidence >= 0 
                            ? '${(result.overallConfidence * 100).toStringAsFixed(1)}%' 
                            : 'Unknown', 
                        accentCyan
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        
        // Heatmap Controls (Only if generated or fallback base64 exists)
        if (canShowHeatmap) ...[
          const SizedBox(height: 16),
          Row(
            children: [
              Switch(
                value: _showHeatmap,
                onChanged: (val) => setState(() => _showHeatmap = val),
                activeColor: accentCyan,
              ),
              const Text('Show XAI Heatmap', style: TextStyle(fontWeight: FontWeight.bold, color: textDark)),
              
              if (_showHeatmap && isOverlay) ...[
                const SizedBox(width: 16),
                const Text('Opacity', style: TextStyle(fontSize: 12, color: textLight)),
                Expanded(
                  child: Slider(
                    value: _heatmapOpacity,
                    min: 0.1,
                    max: 1.0,
                    activeColor: accentCyan,
                    inactiveColor: accentCyan.withOpacity(0.2),
                    onChanged: (val) => setState(() => _heatmapOpacity = val),
                  ),
                ),
              ]
            ],
          ),
        ],
      ],
    );
  }

  Widget _buildOverlayTag(String text, Color dotColor) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: Colors.black.withOpacity(0.6), borderRadius: BorderRadius.circular(12)),
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
        const Text('AI Findings', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
        if (isRedAlert)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(color: const Color(0xFFFFEAEA), borderRadius: BorderRadius.circular(20)),
            child: Row(
              children: const [
                Icon(Icons.error_outline, size: 14, color: alertRed),
                const SizedBox(width: 4),
                Text('Urgent Review', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: alertRed)),
              ],
            ),
          ),
      ],
    );
  }

  Widget _buildAIFindingsList(List<AIFinding> findings) {
    final displayFindings = findings.take(1).toList();
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 15, offset: const Offset(0, 5))],
      ),
      child: Column(
        children: displayFindings.asMap().entries.map((entry) {
          int index = entry.key;
          AIFinding finding = entry.value;
          Color statusColor = finding.riskLevel == 'High' ? alertRed : (finding.riskLevel == 'Moderate' ? alertOrange : alertGreen);

          return Column(
            children: [
              _buildFindingRow(finding.region, finding.observation, finding.riskLevel, finding.confidence, statusColor),
              if (index < displayFindings.length - 1)
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
                            width: 50, height: 4,
                            decoration: BoxDecoration(color: color.withOpacity(0.2), borderRadius: BorderRadius.circular(2)),
                            child: Align(
                              alignment: Alignment.centerLeft,
                              child: Container(width: 50 * percent, height: 4, decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(2))),
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
      decoration: BoxDecoration(color: const Color(0xFFEAF8FC), borderRadius: BorderRadius.circular(20)),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: accentCyan.withOpacity(0.2), borderRadius: BorderRadius.circular(16)),
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

  Widget _buildBottomNav(BuildContext context, bool isDoctor) {
    return Container(
      decoration: BoxDecoration(boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, -5))]),
      child: BottomNavigationBar(
        type: BottomNavigationBarType.fixed,
        backgroundColor: Colors.white,
        selectedItemColor: accentCyan,
        unselectedItemColor: textLight,
        currentIndex: 1,
        onTap: (index) {
          if (index == 0) context.goNamed('dashboard');
          if (index == 1) return;
          if (isDoctor) {
            if (index == 2) context.goNamed('triage');
            if (index == 3) context.goNamed('ai_chat');
          } else {
            if (index == 2) context.goNamed('ai_chat');
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