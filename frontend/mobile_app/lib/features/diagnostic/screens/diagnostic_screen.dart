import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:image_picker/image_picker.dart';
import '../../dashboard/screens/dashboard_screen.dart';

const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);

class DiagnosticScreen extends ConsumerStatefulWidget {
  const DiagnosticScreen({Key? key}) : super(key: key);

  @override
  ConsumerState<DiagnosticScreen> createState() => _DiagnosticScreenState();
}

class _DiagnosticScreenState extends ConsumerState<DiagnosticScreen> {
  int _selectedModuleIndex = 0;

  final ImagePicker _picker = ImagePicker();
  XFile? _selectedImage;

  final List<String> _modules = ['Chest X-Ray', 'ECG', 'Skin'];

  // ==========================================
  // Bottom Sheet for Camera vs Gallery
  // ==========================================
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
    final profileAsync = ref.watch(profileProvider(currentUserId));

    final bool hasFile = _selectedImage != null;

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
            child: profileAsync.when(
              loading: () => const Center(child: CircularProgressIndicator(color: accentCyan)),
              error: (err, stack) => Center(child: Text('Error: $err')),
              data: (profileData) {
                final String userRole = profileData?['userType'] ?? 'Patient';
                final bool isDoctor = userRole.toLowerCase() == 'doctor';

                return Column(
                  children: [
                    Expanded(
                      child: SingleChildScrollView(
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

                            isDoctor ? _buildDoctorTriage() : _buildPatientHistory(),
                            const SizedBox(height: 40),
                          ],
                        ),
                      ),
                    ),

                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
                      child: SizedBox(
                        width: double.infinity,
                        height: 56,
                        child: ElevatedButton(
                          onPressed: hasFile
                              ? () {
                            final selectedScan = _modules[_selectedModuleIndex];
                            context.goNamed(
                                'diagnostic_result',
                                pathParameters: {'module' : selectedScan}
                            );
                          }
                              : null,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: primaryBlue,
                            disabledBackgroundColor: primaryBlue.withOpacity(0.3),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                            ),
                            elevation: hasFile ? 4 : 0,
                          ),
                          child: Row(
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
      bottomNavigationBar: _buildBottomNav(context),
    );
  }

  // ==========================================
  // WIDGET COMPONENTS
  // ==========================================

  Widget _buildHeader() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
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
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(30),
        boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, 5))],
      ),
      child: Row(
        children: List.generate(_modules.length, (index) {
          final isSelected = _selectedModuleIndex == index;
          return Expanded(
            child: GestureDetector(
              onTap: () {
                setState(() {
                  _selectedModuleIndex = index;
                  _selectedImage = null;
                });
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
      onTap: _pickImageSource,
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

  Widget _buildDoctorTriage() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text('Triage Dashboard', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: const Color(0xFFFFEAEA), borderRadius: BorderRadius.circular(12)),
              child: const Text('Priority First', style: TextStyle(color: Color(0xFFE63946), fontSize: 10, fontWeight: FontWeight.bold)),
            ),
          ],
        ),
        const SizedBox(height: 16),
        _buildTriageCard('Ahmad R.', 'Left Lower Lobe (GGO)', 'High Risk', const Color(0xFFE63946), '10m ago'),
        const SizedBox(height: 12),
        _buildTriageCard('Sarah M.', 'Pleural Effusion', 'Moderate', const Color(0xFFF2994A), '1h ago'),
        const SizedBox(height: 12),
        _buildTriageCard('Usman K.', 'Normal Borders', 'Low Risk', const Color(0xFF00A36C), '3h ago'),
      ],
    );
  }

  Widget _buildTriageCard(String patientName, String finding, String risk, Color riskColor, String time) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: riskColor.withOpacity(0.3)),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(patientName, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: textDark)),
              const SizedBox(height: 4),
              Text(finding, style: const TextStyle(fontSize: 12, color: textLight)),
            ],
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(risk, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14, color: riskColor)),
              const SizedBox(height: 4),
              Text(time, style: const TextStyle(fontSize: 11, color: textLight)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildPatientHistory() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Your Scan History', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
        const SizedBox(height: 16),
        _buildHistoryCard('Chest X-Ray', 'April 10, 2026', 'Reviewed by Dr. Ali', Icons.monitor_heart),
        const SizedBox(height: 12),
        _buildHistoryCard('ECG Analysis', 'March 22, 2026', 'Normal Rhythm', Icons.show_chart),
      ],
    );
  }

  Widget _buildHistoryCard(String title, String date, String status, IconData icon) {
    return Container(
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
                Text(title, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15, color: textDark)),
                const SizedBox(height: 4),
                Text(status, style: const TextStyle(fontSize: 12, color: textLight)),
              ],
            ),
          ),
          Text(date, style: const TextStyle(fontSize: 12, color: textLight, fontWeight: FontWeight.w500)),
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