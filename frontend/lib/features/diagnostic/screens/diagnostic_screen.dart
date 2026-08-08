// lib/features/diagnostic/screens/diagnostic_screen.dart
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediscanx_mobile/core/database/supabase_connector.dart';
import 'package:mediscanx_mobile/features/dashboard/services/doctor_patient_profile_service.dart';
import 'package:mediscanx_mobile/features/diagnostic/providers/cloud_diagnostic_provider.dart';
import 'package:mediscanx_mobile/features/diagnostic/providers/skin_diagnostic_provider.dart';
import 'package:mediscanx_mobile/core/utils/error_helper.dart';
import 'package:mediscanx_mobile/core/utils/image_validator.dart';

// --- STRICT PACKAGE IMPORTS ---
import 'package:mediscanx_mobile/core/database/database_manager.dart';
import 'package:mediscanx_mobile/features/diagnostic/services/scan_dao.dart';
import 'package:mediscanx_mobile/features/diagnostic/models/diagnostic_result.dart';
import 'package:mediscanx_mobile/features/diagnostic/providers/scan_history_provider.dart';
import 'package:mediscanx_mobile/features/diagnostic/providers/diagnostic_service.dart';

const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);

// ==========================================
// SHARED ROUTING STATE
// ==========================================
final diagnosticModuleIndexProvider = StateProvider<int>((ref) => 0);

class DiagnosticScreen extends ConsumerStatefulWidget {
  const DiagnosticScreen({Key? key}) : super(key: key);

  @override
  ConsumerState<DiagnosticScreen> createState() => _DiagnosticScreenState();
}

class _DiagnosticScreenState extends ConsumerState<DiagnosticScreen> {
  final ImagePicker _picker = ImagePicker();
  XFile? _selectedImage;

  bool _isProcessing = false;

  final List<String> _modules = ['Chest X-Ray', 'ECG', 'Skin'];

  Future<void> _pickImageSource() async {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (BuildContext context) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 16.0),
            child: Wrap(
              children: <Widget>[
                const Padding(
                  padding: EdgeInsets.only(left: 24.0, bottom: 8.0, top: 8.0),
                  child: Text(
                    'Upload Scan Data',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: primaryBlue),
                  ),
                ),
                ListTile(
                  leading: const Icon(Icons.camera_alt_rounded, color: accentCyan),
                  title: const Text('Take a Photo', style: TextStyle(fontWeight: FontWeight.w500)),
                  subtitle: const Text('Use device camera', style: TextStyle(fontSize: 12)),
                  onTap: () async {
                    Navigator.of(context).pop();
                    final XFile? image = await _picker.pickImage(source: ImageSource.camera);
                    if (image != null) setState(() => _selectedImage = image);
                  },
                ),
                ListTile(
                  leading: const Icon(Icons.photo_library_rounded, color: accentCyan),
                  title: const Text('Upload from Device', style: TextStyle(fontWeight: FontWeight.w500)),
                  subtitle: const Text('Select saved image or document', style: TextStyle(fontSize: 12)),
                  onTap: () async {
                    Navigator.of(context).pop();
                    final XFile? image = await _picker.pickImage(source: ImageSource.gallery);
                    if (image != null) setState(() => _selectedImage = image);
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final currentUserId = Supabase.instance.client.auth.currentUser?.id ?? 'ID-PENDING';
    final role = (Supabase.instance.client.auth.currentUser?.userMetadata?['role'] ??
        Supabase.instance.client.auth.currentUser?.userMetadata?['userType'])
        ?.toString()
        .toLowerCase();
    final bool isDoctor = role == 'doctor';

    final profileAsync = const AsyncValue.data(true);
    final scanHistoryAsync = ref.watch(userScanHistoryProvider(currentUserId));

    final bool hasFile = _selectedImage != null;

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
            child: profileAsync.when(
              loading: () => const Center(child: CircularProgressIndicator(color: accentCyan)),
              error: (err, stack) => Center(child: Text('Error: $err')),
              data: (_) {
                return Column(
                  children: [
                    Expanded(
                      child: RefreshIndicator(
                        color: accentCyan,
                        onRefresh: () async {
                          ref.invalidate(userScanHistoryProvider(currentUserId));
                        },
                        child: SingleChildScrollView(
                          physics: const AlwaysScrollableScrollPhysics(),
                          padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              _buildHeader(),
                              const SizedBox(height: 24),
                              _buildModuleToggle(),
                              const SizedBox(height: 24),
                              _buildUploadBlock(hasFile),
                              const SizedBox(height: 32),
                              _buildScanHistorySection(scanHistoryAsync, title: 'Recent Scan History'),
                              const SizedBox(height: 40),
                            ],
                          ),
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
                      child: SizedBox(
                        width: double.infinity,
                        height: 56,
                        child: ElevatedButton(
                          onPressed: (hasFile && !_isProcessing)
                              ? () async {
                            final currentIndex = ref.read(diagnosticModuleIndexProvider);
                            final selectedScan = _modules[currentIndex];

                            if (selectedScan == 'Chest X-Ray' || selectedScan == 'Skin' || selectedScan == 'ECG') {
                              setState(() => _isProcessing = true);

                              try {
                                if (isDoctor) {
                                  final service = ref.read(doctorPatientProfileServiceProvider);
                                  final hasProfile = await service.hasPatientProfile(currentUserId);
                                  if (!hasProfile) {
                                    final db = DatabaseManager.drift;
                                    final doctorRecord = await db.getDoctor(currentUserId);
                                    if (doctorRecord != null) {
                                      await service.createPatientProfileForDoctor(doctorRecord);
                                    }
                                  }
                                }

                                final imageFile = File(_selectedImage!.path);

                                // Validate the image matches the selected modality
                                final validationError = await ImageValidator.validate(imageFile, selectedScan);
                                if (validationError != null) {
                                  if (mounted) {
                                    setState(() => _isProcessing = false);
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(
                                        content: Text(validationError),
                                        backgroundColor: Colors.red,
                                        duration: const Duration(seconds: 4),
                                      ),
                                    );
                                  }
                                  return;
                                }

                                DiagnosticResult? realAiResult;

                                if (selectedScan == 'Chest X-Ray') {
                                  realAiResult = await ref.read(analyzeXRayProvider)(imageFile);
                                } else if (selectedScan == 'ECG') {
                                  realAiResult = await ref.read(analyzeECGProvider)(imageFile);
                                } else if (selectedScan == 'Skin') {
                                  realAiResult = await ref.read(analyzeSkinProvider)(imageFile);
                                }

                                if (realAiResult != null && mounted) {
                                  final dao = ScanDao(DatabaseManager.drift);
                                  await dao.insertScan(realAiResult, currentUserId);

                                  setState(() {
                                    _selectedImage = null;
                                    _isProcessing = false;
                                  });

                                  context.pushNamed(
                                    'diagnostic_result',
                                    pathParameters: {'module': selectedScan},
                                    extra: realAiResult,
                                  );
                                } else {
                                  if (mounted) setState(() => _isProcessing = false);
                                }
                              } catch (e) {
                                if (mounted) {
                                  setState(() => _isProcessing = false);
                                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(ErrorHelper.getHumanReadableError(e)), backgroundColor: Colors.red));
                                }
                                debugPrint('Error running inference: $e');
                              }
                            } else {
                              context.pushNamed(
                                'diagnostic_result',
                                pathParameters: {'module': selectedScan},
                              );
                            }
                          }
                              : null,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: primaryBlue,
                            disabledBackgroundColor: primaryBlue.withOpacity(0.3),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                            ),
                            elevation: (hasFile && !_isProcessing) ? 4 : 0,
                          ),
                          child: _isProcessing
                              ? const SizedBox(
                              height: 24,
                              width: 24,
                              child: CircularProgressIndicator(color: Colors.white, strokeWidth: 3)
                          )
                              : Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.auto_awesome, color: hasFile ? Colors.white : Colors.white70),
                              const SizedBox(width: 8),
                              Text(
                                'Perform Diagnosis',
                                style: TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.bold,
                                  color: hasFile ? Colors.white : Colors.white70,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ],
                );
              },
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
              Text('Diagnostic Hub', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: primaryBlue)),
              Text(
                'Select module and capture data',
                style: TextStyle(fontSize: 13, color: textLight),
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
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

  Widget _buildModuleToggle() {
    final currentModuleIndex = ref.watch(diagnosticModuleIndexProvider);

    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(30),
        boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 5))],
      ),
      child: Row(
        children: List.generate(_modules.length, (index) {
          final isSelected = currentModuleIndex == index;
          return Expanded(
            child: GestureDetector(
              onTap: () {
                ref.read(diagnosticModuleIndexProvider.notifier).state = index;
                setState(() => _selectedImage = null);
              },
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding: const EdgeInsets.symmetric(vertical: 12),
                decoration: BoxDecoration(
                  color: isSelected ? primaryBlue : Colors.transparent,
                  borderRadius: BorderRadius.circular(26),
                ),
                child: Center(
                  child: Text(
                    _modules[index],
                    style: TextStyle(
                      color: isSelected ? Colors.white : textLight,
                      fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
                      fontSize: 14,
                    ),
                  ),
                ),
              ),
            ),
          );
        }),
      ),
    );
  }

  Widget _buildUploadBlock(bool hasFile) {
    return GestureDetector(
      onTap: () => _isProcessing ? null : _pickImageSource(),
      child: Container(
        height: 220,
        width: double.infinity,
        decoration: BoxDecoration(
          color: hasFile ? const Color(0xFFEAF8FC) : Colors.white,
          borderRadius: BorderRadius.circular(24),
          border: Border.all(
            color: hasFile ? accentCyan : primaryBlue.withOpacity(0.1),
            width: 2,
          ),
          boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, 5))],
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: hasFile ? accentCyan.withOpacity(0.2) : bgLight,
                shape: BoxShape.circle,
              ),
              child: Icon(
                hasFile ? Icons.check_circle_rounded : Icons.cloud_upload_rounded,
                size: 40,
                color: hasFile ? accentCyan : primaryBlue,
              ),
            ),
            const SizedBox(height: 16),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24.0),
              child: Text(
                hasFile ? _selectedImage!.name : 'Upload or Capture Data',
                textAlign: TextAlign.center,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: textDark),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              hasFile ? 'Tap to change file' : 'Tap to open camera or gallery',
              style: const TextStyle(fontSize: 12, color: textLight),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildScanHistorySection(AsyncValue<List<DiagnosticResult>> scanHistoryAsync, {required String title}) {
    return scanHistoryAsync.when(
      loading: () => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
          const SizedBox(height: 16),
          const Center(child: CircularProgressIndicator(color: accentCyan)),
        ],
      ),
      error: (err, stack) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
          const SizedBox(height: 8),
          Text('Failed to load scan history: $err', style: const TextStyle(color: textLight)),
        ],
      ),
      data: (scans) {
        if (scans.isEmpty) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
              const SizedBox(height: 12),
              const Text('No scans yet. Your history will appear here.', style: TextStyle(fontSize: 12, color: textLight)),
            ],
          );
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
            const SizedBox(height: 16),
            for (final scan in scans) ...[
              _buildScanHistoryCard(scan),
              const SizedBox(height: 12),
            ],
          ],
        );
      },
    );
  }

  Widget _buildScanHistoryCard(DiagnosticResult scan) {
    final statusLabel = _scanStatusLabel(scan);
    final scanDate = _formatScanDate(scan.scanDate.toLocal());
    final icon = _scanTypeIcon(scan.scanType);
    final riskLabel = _riskLabelForScan(scan);
    final riskColor = _riskColorForScan(riskLabel);

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: () {
          context.pushNamed(
            'diagnostic_result',
            pathParameters: {'module': scan.scanType},
            extra: scan,
          );
        },
        borderRadius: BorderRadius.circular(16),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.03), blurRadius: 10, offset: const Offset(0, 4))],
          ),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(color: const Color(0xFFEAF8FC), borderRadius: BorderRadius.circular(12)),
                child: Icon(icon, color: accentCyan, size: 20),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(scan.scanType, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15, color: textDark)),
                    const SizedBox(height: 4),
                    Text(statusLabel, style: const TextStyle(fontSize: 12, color: textLight), maxLines: 1, overflow: TextOverflow.ellipsis),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(scanDate, style: const TextStyle(fontSize: 12, color: textLight, fontWeight: FontWeight.w500)),
                  const SizedBox(height: 2),
                  Text('${(scan.scanDate.toLocal().hour % 12 == 0 ? 12 : scan.scanDate.toLocal().hour % 12)}:${scan.scanDate.toLocal().minute.toString().padLeft(2, '0')} ${scan.scanDate.toLocal().hour >= 12 ? 'PM' : 'AM'}', style: const TextStyle(fontSize: 10, color: textLight)),
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
      ),
    );
  }

  String _riskLabelForScan(DiagnosticResult scan) {
    if (scan.scanStatus == 2) return 'High Risk';
    if (scan.scanStatus == 1) return 'Warning';
    return 'Normal';
  }

  Color _riskColorForScan(String riskLabel) {
    if (riskLabel == 'High Risk') return const Color(0xFFE63946);
    if (riskLabel == 'Warning') return const Color(0xFFF2994A);
    return const Color(0xFF00A36C);
  }

  IconData _scanTypeIcon(String scanType) {
    if (scanType.contains('Chest')) return Icons.monitor_heart;
    if (scanType.contains('ECG')) return Icons.show_chart;
    if (scanType.contains('Skin')) return Icons.image_outlined;
    return Icons.medical_services;
  }

  String _scanStatusLabel(DiagnosticResult scan) {
    if (scan.tags.isNotEmpty) return scan.tags.first;
    return 'Completed';
  }

  String _formatScanDate(DateTime date) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return '${months[date.month - 1]} ${date.day}, ${date.year}';
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
        currentIndex: 1,
        selectedLabelStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
        unselectedLabelStyle: const TextStyle(fontSize: 12),
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