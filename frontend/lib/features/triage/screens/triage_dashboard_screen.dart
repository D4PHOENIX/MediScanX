import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../providers/triage_provider.dart';
import '../services/triage_api_service.dart';

const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);

class TriageDashboardScreen extends ConsumerWidget {
  const TriageDashboardScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = Supabase.instance.client.auth.currentUser;
    final rawRole = (user?.userMetadata?['role'] ?? user?.userMetadata?['userType'])
        ?.toString()
        .toLowerCase();
    final isDoctor = rawRole == 'doctor';

    if (!isDoctor) {
      return Scaffold(
        backgroundColor: bgLight,
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.lock_outline, size: 64, color: primaryBlue),
                const SizedBox(height: 16),
                const Text(
                  'Triage is available for doctors only.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: textDark, fontSize: 16),
                ),
                const SizedBox(height: 24),
                ElevatedButton(
                  onPressed: () => context.goNamed('dashboard'),
                  child: const Text('Back to Dashboard'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final triageAsync = ref.watch(triageQueueProvider);

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
                errorBuilder: (context, error, stackTrace) =>
                    const Icon(Icons.masks_outlined, size: 400, color: primaryBlue),
              ),
            ),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildHeader(context),
                  const SizedBox(height: 24),
                  Expanded(
                    child: triageAsync.when(
                      loading: () => const Center(
                        child: CircularProgressIndicator(color: accentCyan),
                      ),
                      error: (err, stack) {
                        // 403 - the caller is not a registered doctor
                        if (err is TriageAccessDeniedException) {
                          return Center(
                            child: Padding(
                              padding: const EdgeInsets.all(24),
                              child: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  const Icon(Icons.lock_outline, size: 64, color: primaryBlue),
                                  const SizedBox(height: 16),
                                  const Text(
                                    'Triage is available for doctor accounts only.',
                                    textAlign: TextAlign.center,
                                    style: TextStyle(color: textDark, fontSize: 16),
                                  ),
                                  const SizedBox(height: 8),
                                  const Text(
                                    'If you are a doctor, please make sure your profile is set up correctly.',
                                    textAlign: TextAlign.center,
                                    style: TextStyle(color: textLight, fontSize: 13),
                                  ),
                                  const SizedBox(height: 24),
                                  ElevatedButton(
                                    onPressed: () => context.goNamed('dashboard'),
                                    style: ElevatedButton.styleFrom(backgroundColor: primaryBlue),
                                    child: const Text('Back to Dashboard', style: TextStyle(color: Colors.white)),
                                  ),
                                ],
                              ),
                            ),
                          );
                        }
                        // Any other error (network, server, etc.)
                        return Center(
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              const Icon(Icons.cloud_off, size: 48, color: textLight),
                              const SizedBox(height: 16),
                              const Text(
                                'Could not load the triage queue.',
                                style: TextStyle(color: textDark, fontSize: 15),
                              ),
                              const SizedBox(height: 8),
                              const Text(
                                'Please check your connection and try again.',
                                style: TextStyle(color: textLight, fontSize: 13),
                              ),
                              const SizedBox(height: 16),
                              TextButton.icon(
                                onPressed: () => ref.invalidate(triageQueueProvider),
                                icon: const Icon(Icons.refresh, size: 18),
                                label: const Text('Retry'),
                              ),
                            ],
                          ),
                        );
                      },
                      data: (scans) {
                        if (scans.isEmpty) {
                          return const Center(
                            child: Text(
                              'No scans available for triage yet.',
                              style: TextStyle(color: textLight),
                            ),
                          );
                        }

                        return ListView.separated(
                          itemCount: scans.length,
                          separatorBuilder: (_, __) => const SizedBox(height: 12),
                          itemBuilder: (context, index) {
                            return _buildTriageCard(context, scans[index]);
                          },
                        );
                      },
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
      bottomNavigationBar: _buildBottomNav(context),
    );
  }

  Widget _buildHeader(BuildContext context) {
    final canGoBack = context.canPop();
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
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
        const Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Triage Dashboard',
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: primaryBlue),
              ),
              SizedBox(height: 4),
              Text(
                'High-risk scans are auto-prioritized',
                style: TextStyle(fontSize: 13, color: textLight),
              ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: const Color(0xFFE6F7F0),
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: const Color(0xFFB3E6D0)),
          ),
          child: const Row(
            children: [
              Icon(Icons.priority_high, size: 12, color: Color(0xFF00A36C)),
              SizedBox(width: 4),
              Text('Active', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF00A36C))),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildTriageCard(BuildContext context, TriageItem item) {
    final riskLabel = _riskLabel(item.scanStatus);
    final riskColor = _riskColor(item.scanStatus);
    final typeLabel = _scanTypeLabel(item.modality);
    final scanDate = _formatScanDate(item.scanDate.toLocal());

    return GestureDetector(
      onTap: () {
        if (item.reportUrl.isNotEmpty) {
          showDialog(
            context: context,
            builder: (context) => Dialog(
              backgroundColor: Colors.transparent,
              child: Stack(
                alignment: Alignment.topRight,
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: InteractiveViewer(
                      child: Image.network(
                        item.reportUrl,
                        headers: {
                          'Authorization': 'Bearer ${Supabase.instance.client.auth.currentSession?.accessToken}'
                        },
                        errorBuilder: (context, error, stackTrace) {
                          return Container(
                            color: Colors.white,
                            padding: const EdgeInsets.all(20),
                            child: const Text('Failed to load image. Ensure you have internet access.'),
                          );
                        },
                      ),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.cancel, color: Colors.red, size: 32),
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),
            ),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('No visual heatmap available for this scan.')),
          );
        }
      },
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: riskColor.withOpacity(0.2)),
          boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.03), blurRadius: 10, offset: const Offset(0, 4))],
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: riskColor.withOpacity(0.1),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(_scanTypeIcon(item.modality), color: riskColor, size: 20),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(typeLabel, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15, color: textDark)),
                  const SizedBox(height: 4),
                  Text('${item.patientName ?? item.patientUsername ?? item.patientRef} • ${(item.confidence * 100).toStringAsFixed(1)}%', style: const TextStyle(fontSize: 12, color: textLight)),
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(scanDate, style: const TextStyle(fontSize: 12, color: textLight, fontWeight: FontWeight.w500)),
                const SizedBox(height: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: riskColor.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    riskLabel,
                    style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: riskColor),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _riskLabel(int scanStatus) {
    switch (scanStatus) {
      case 2:
        return 'High Risk';
      case 1:
        return 'Moderate';
      case 0:
        return 'Normal';
      default:
        return 'Normal';
    }
  }

  Color _riskColor(int scanStatus) {
    switch (scanStatus) {
      case 2:
        return const Color(0xFFE63946);
      case 1:
        return const Color(0xFFF2994A);
      case 0:
        return const Color(0xFF00A36C);
      default:
        return const Color(0xFF00A36C);
    }
  }

  String _scanTypeLabel(String modality) {
    switch (modality.toLowerCase()) {
      case 'cxr':
        return 'Chest X-Ray';
      case 'ecg':
        return 'ECG Analysis';
      case 'skin':
        return 'Skin Lesion';
      default:
        return 'Diagnostic Scan';
    }
  }

  IconData _scanTypeIcon(String modality) {
    switch (modality.toLowerCase()) {
      case 'cxr':
        return Icons.monitor_heart;
      case 'ecg':
        return Icons.show_chart;
      case 'skin':
        return Icons.image_outlined;
      default:
        return Icons.medical_services;
    }
  }

  String _formatScanDate(DateTime date) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final month = months[date.month - 1];
    return '$month ${date.day}, ${date.year}';
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
        currentIndex: 2,
        selectedLabelStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
        unselectedLabelStyle: const TextStyle(fontSize: 12),
        onTap: (index) {
          if (index == 0) context.goNamed('dashboard');
          if (index == 1) context.goNamed('diagnostic');
          if (index == 2) return;
          if (index == 3) context.goNamed('ai_chat');
        },
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.dashboard_rounded), label: 'Dashboard'),
          BottomNavigationBarItem(icon: Icon(Icons.analytics_outlined), label: 'Diagnostic'),
          BottomNavigationBarItem(icon: Icon(Icons.priority_high), label: 'Triage'),
          BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'AI Chat'),
        ],
      ),
    );
  }
}
