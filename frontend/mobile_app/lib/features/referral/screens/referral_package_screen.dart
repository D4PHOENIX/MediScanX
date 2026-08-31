import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

// Shared Colors (Defined in-file for independence, use constants file later)
const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);

// Status/Alert Colors from image
const Color alertRed = Color(0xFFE63946);
const Color accentGreen = Color(0xFF00A36C);
const Color vitalsOrange = Color(0xFFF2994A);

class ReferralPackageScreen extends StatelessWidget {
  const ReferralPackageScreen({Key? key}) : super(key: key);

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

                // Scrollable Content Area
                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.symmetric(horizontal: 24.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [


                        _buildQRTransferCard(),
                        const SizedBox(height: 16),

                        _buildParamedicProfile(),
                        const SizedBox(height: 24),

                        // Final Download Button at the bottom of the scroll
                        _buildDownloadButton(context),
                        const SizedBox(height: 32), // Extra padding at bottom
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      // Active navigation index is now set to 3 (Referral)
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
              Text('Referral Package', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: primaryBlue)),
              SizedBox(height: 4),
              Text(
                'Secure transfer of clinical data',
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
              Icon(Icons.wifi, size: 12, color: accentGreen),
              SizedBox(width: 4),
              Text('Offline-First', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: accentGreen)),
            ],
          ),
        ),
      ],
    );
  }



  Widget _buildVitalCard(IconData icon, String value, String label, Color statColor) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.03), blurRadius: 10, offset: const Offset(0, 4))],
      ),
      child: Column(
        children: [
          Icon(icon, color: statColor.withOpacity(0.6), size: 18),
          const SizedBox(height: 8),
          Text(value, style: TextStyle(color: statColor, fontWeight: FontWeight.bold, fontSize: 16)),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(color: textLight, fontSize: 11)),
        ],
      ),
    );
  }

  Widget _buildQRTransferCard() {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(24),
        boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, 5))],
      ),
      child: Column(
        children: [
          const Text('Secure QR Transfer Code', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: primaryBlue)),
          const SizedBox(height: 4),
          const Text(
            'Present at the receiving facility for instant record transfer',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, color: textLight),
          ),
          const SizedBox(height: 32),

          // THE QR CODE (Stylized from image)
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              border: Border.all(color: accentCyan, width: 2), // The colored border frame
              borderRadius: BorderRadius.circular(8),
            ),
            child: Stack(
              children: [
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: accentCyan.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: const Icon(Icons.qr_code_scanner_rounded, size: 180, color: accentCyan),
                ),
                // Add the corner bracket decoration from image
                Positioned(top: 0, left: 0, child: _buildQRCorner(0, 0)),
                Positioned(top: 0, right: 0, child: _buildQRCorner(0, 90)),
                Positioned(bottom: 0, left: 0, child: _buildQRCorner(180, 0)),
                Positioned(bottom: 0, right: 0, child: _buildQRCorner(180, 90)),
              ],
            ),
          ),

          const SizedBox(height: 32),

          // SECURITY DETAILS AREA
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: const Color(0xFFE6F7F0), borderRadius: BorderRadius.circular(12)),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.verified_user_rounded, color: accentGreen, size: 16),
                const SizedBox(width: 8),
                const Text(
                  '256-bit encrypted · HL7 FHIR R4',
                  style: TextStyle(color: accentGreen, fontSize: 11, fontWeight: FontWeight.bold),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          const Text('Generated 10/03/2026, 15:11:59', style: TextStyle(color: textLight, fontSize: 10)),
        ],
      ),
    );
  }

  // Bracket corners for the QR code
  Widget _buildQRCorner(double turnDegree, double rotateDegree) {
    return RotatedBox(
      quarterTurns: (turnDegree / 90).round(),
      child: Transform.rotate(
        angle: rotateDegree * (3.14159 / 180),
        child: Container(
          width: 24,
          height: 24,
          decoration: const BoxDecoration(
            border: Border(
              top: BorderSide(color: accentCyan, width: 4),
              left: BorderSide(color: accentCyan, width: 4),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildParamedicProfile() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.03), blurRadius: 10, offset: const Offset(0, 4))],
      ),
      child: Row(
        children: [
          // Avatar Icon from dashboard screen
          Container(
            padding: const EdgeInsets.all(8),
            decoration: const BoxDecoration(color: Color(0xFFEAF8FC), shape: BoxShape.circle),
            child: const Icon(Icons.person_outline_rounded, color: accentCyan, size: 24),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Referring Paramedic', style: TextStyle(color: textLight, fontSize: 11)),
                const SizedBox(height: 4),
                const Text('Paramedic A. Singh', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: textDark)),
              ],
            ),
          ),
          // Verified Badge from image
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(color: const Color(0xFFE6F7F0), borderRadius: BorderRadius.circular(20)),
            child: Row(
              children: const [
                Icon(Icons.check_circle_rounded, color: accentGreen, size: 12),
                SizedBox(width: 6),
                Text('Verified', style: TextStyle(color: accentGreen, fontWeight: FontWeight.bold, fontSize: 11)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // Large Action Button at the very bottom
  Widget _buildDownloadButton(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 56,
      child: ElevatedButton(
        onPressed: () {
          // Add your platform-specific PDF download logic here later
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Downloading Referral PDF Report...')));
        },
        style: ElevatedButton.styleFrom(
          backgroundColor: accentGreen, // Same green as vitals alert
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          elevation: 4,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: const [
            Icon(Icons.download_rounded, color: Colors.white),
            SizedBox(width: 12),
            Text(
              'Download Report (PDF)',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white),
            ),
          ],
        ),
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
        currentIndex: 3, // Set to index 3 (Referral Package)
        selectedLabelStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
        unselectedLabelStyle: const TextStyle(fontSize: 12),
        onTap: (index) {
          if (index == 0) context.goNamed('dashboard');
          if (index == 1) context.goNamed('diagnostic');
          if (index == 2) context.goNamed('ai_chat');
          if (index == 3) return;
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