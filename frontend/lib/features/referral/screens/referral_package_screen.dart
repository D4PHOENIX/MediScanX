// lib/features/referral/screens/referral_package_screen.dart
import 'dart:io';
import 'dart:ui' as ui;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gal/gal.dart';
import 'package:go_router/go_router.dart';
import 'package:path_provider/path_provider.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/utils/download_service.dart';
import '../providers/referral_provider.dart';

// Shared Colors
const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);
const Color alertRed = Color(0xFFE63946);
const Color accentGreen = Color(0xFF00A36C);
const Color vitalsOrange = Color(0xFFF2994A);

class ReferralPackageScreen extends ConsumerStatefulWidget {
  final String? patientId;
  final List<String>? scanIds;

  const ReferralPackageScreen({
    Key? key,
    this.patientId,
    this.scanIds,
  }) : super(key: key);

  @override
  ConsumerState<ReferralPackageScreen> createState() => _ReferralPackageScreenState();
}

class _ReferralPackageScreenState extends ConsumerState<ReferralPackageScreen> {
  bool _isDownloading = false;
  bool _showQR = false;
  final GlobalKey _qrKey = GlobalKey();

  @override
  void initState() {
    super.initState();
    if (widget.patientId != null && widget.scanIds != null && widget.scanIds!.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        ref.read(referralProvider.notifier).submitReferral(
          patientId: widget.patientId!,
          scanIds: widget.scanIds!,
        );
      });
    }
  }

  // =========================================================================
  // ACTIONS
  // =========================================================================

  Future<void> _downloadReport(String url) async {
    final uri = Uri.tryParse(url);
    if (uri == null) {
      debugPrint('🔴 Invalid URL: $url');
      return;
    }

    setState(() {
      _isDownloading = true;
    });

    try {
      final filename = 'MediScanX_Report_${DateTime.now().millisecondsSinceEpoch}.pdf';
      final savedFile = await DownloadService().downloadFile(url, filename);

      if (savedFile != null && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Row(
              children: const [
                Icon(Icons.check_circle_rounded, color: Colors.white, size: 18),
                SizedBox(width: 8),
                Expanded(child: Text('Report saved to internal Downloads!')),
              ],
            ),
            backgroundColor: accentGreen,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          ),
        );
      } else {
        throw Exception('Download failed');
      }
    } catch (e) {
      debugPrint('🔴 Download failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Failed to download report. Please try again.'),
            backgroundColor: alertRed,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _isDownloading = false;
        });
      }
    }
  }

  Future<void> _saveQrToGallery() async {
    try {
      final boundary = _qrKey.currentContext?.findRenderObject() as RenderRepaintBoundary?;
      if (boundary == null) return;

      final image = await boundary.toImage(pixelRatio: 3.0);
      final byteData = await image.toByteData(format: ui.ImageByteFormat.png);
      if (byteData == null) return;

      final bytes = byteData.buffer.asUint8List();
      final filename = 'MediScanX_QR_${DateTime.now().millisecondsSinceEpoch}.png';

      // 1. Save to Gallery (Gal) - for user convenience
      final tempDir = await getTemporaryDirectory();
      final tempFilePath = '${tempDir.path}/$filename';
      final tempFile = File(tempFilePath);
      await tempFile.writeAsBytes(bytes);
      await Gal.putImage(tempFilePath);

      // 2. Save to internal downloads (for in-app display)
      await DownloadService().saveBytes(bytes, filename);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Row(
              children: const [
                Icon(Icons.check_circle_rounded, color: Colors.white, size: 18),
                SizedBox(width: 8),
                Expanded(child: Text('QR code saved to Gallery and internal Downloads!')),
              ],
            ),
            backgroundColor: accentGreen,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          ),
        );
      }
    } catch (e) {
      debugPrint('🔴 QR save failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Failed to save QR code. Check storage permissions.'),
            backgroundColor: alertRed,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          ),
        );
      }
    }
  }

  // =========================================================================
  // BUILD
  // =========================================================================

  @override
  Widget build(BuildContext context) {
    final referralState = ref.watch(referralProvider);
    final bool hasData = referralState.response != null;
    final bool isLoading = referralState.isLoading;
    final signedUrl = hasData ? referralState.response!.signedUrl : '';

    return Scaffold(
      backgroundColor: bgLight,
      body: Stack(
        children: [
          // Watermark
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

          // Content
          SafeArea(
            child: Column(
              children: [
                // Header
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
                  child: _buildHeader(hasData),
                ),

                // Scrollable body
                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.symmetric(horizontal: 24.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // Status Card
                        _buildStatusCard(referralState, isLoading, hasData),
                        const SizedBox(height: 20),

                        // Action Buttons — fade in when ready
                        AnimatedOpacity(
                          opacity: hasData ? 1.0 : 0.4,
                          duration: const Duration(milliseconds: 500),
                          child: Column(
                            children: [
                              _buildDownloadButton(signedUrl, hasData, isLoading),
                              const SizedBox(height: 12),
                              _buildGenerateQRButton(signedUrl, hasData, isLoading),
                            ],
                          ),
                        ),
                        const SizedBox(height: 20),

                        // QR Code Display (toggleable)
                        if (_showQR && hasData && signedUrl.isNotEmpty)
                          _buildQRDisplay(signedUrl),

                        const SizedBox(height: 32),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // =========================================================================
  // HEADER
  // =========================================================================

  Widget _buildHeader(bool isCloudActive) {
    final canGoBack = context.canPop();
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
                boxShadow: [
                  BoxShadow(color: primaryBlue.withOpacity(0.08), blurRadius: 8, offset: const Offset(0, 2)),
                ],
              ),
              child: const Icon(Icons.arrow_back_ios_new_rounded, size: 16, color: primaryBlue),
            ),
          ),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: const [
              Text('Share Report', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: primaryBlue)),
              SizedBox(height: 4),
              Text(
                'Download or share via QR code',
                style: TextStyle(fontSize: 13, color: textLight),
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: isCloudActive ? const Color(0xFFE6F7F0) : vitalsOrange.withOpacity(0.1),
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: isCloudActive ? const Color(0xFFB3E6D0) : vitalsOrange.withOpacity(0.3)),
          ),
          child: Row(
            children: [
              Icon(
                isCloudActive ? Icons.cloud_done_rounded : Icons.hourglass_top_rounded,
                size: 12,
                color: isCloudActive ? accentGreen : vitalsOrange,
              ),
              const SizedBox(width: 4),
              Text(
                isCloudActive ? 'Ready' : 'Pending',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  color: isCloudActive ? accentGreen : vitalsOrange,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  // =========================================================================
  // STATUS CARD - replaces the old QR Transfer Card
  // =========================================================================

  Widget _buildStatusCard(dynamic referralState, bool isLoading, bool hasData) {
    final bool hasError = referralState.errorMessage != null;
    final bool isWaiting = isLoading || (!hasData && !hasError);

    Widget statusWidget;
    if (hasData) {
      statusWidget = _buildSuccessState();
    } else if (hasError) {
      statusWidget = _buildErrorState(referralState.errorMessage!);
    } else {
      statusWidget = _buildWaitingState();
    }

    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, 5)),
        ],
      ),
      child: Column(
        children: [
          // Step indicator
          _buildStepIndicator(isWaiting, hasData),
          const SizedBox(height: 24),

          // Main status content
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 500),
            switchInCurve: Curves.easeOut,
            switchOutCurve: Curves.easeIn,
            child: statusWidget,
          ),

          const SizedBox(height: 20),

          // Security badge
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: BoxDecoration(
              color: hasData
                  ? const Color(0xFFE6F7F0)
                  : hasError
                      ? alertRed.withOpacity(0.06)
                      : const Color(0xFFF0F4F8),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  Icons.verified_user_rounded,
                  color: hasData ? accentGreen : (hasError ? alertRed : textLight),
                  size: 16,
                ),
                const SizedBox(width: 8),
                Text(
                  '256-bit encrypted · HL7 FHIR R4',
                  style: TextStyle(
                    color: hasData ? accentGreen : (hasError ? alertRed.withOpacity(0.6) : textLight),
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
          ),

          if (hasData) ...[
            const SizedBox(height: 12),
            Text(
              'Generated ${DateTime.now().toString().substring(0, 16)}',
              style: const TextStyle(color: textLight, fontSize: 10),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildStepIndicator(bool isWaiting, bool hasData) {
    return Row(
      children: [
        // Step 1
        Expanded(
          child: Container(
            height: 4,
            decoration: BoxDecoration(
              color: accentCyan,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        ),
        const SizedBox(width: 8),
        // Step 2
        Expanded(
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 600),
            height: 4,
            decoration: BoxDecoration(
              color: hasData ? accentGreen : textLight.withOpacity(0.2),
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildWaitingState() {
    return Column(
      key: const ValueKey('waiting'),
      children: [
        SizedBox(
          width: 72,
          height: 72,
          child: Stack(
            alignment: Alignment.center,
            children: [
              SizedBox(
                width: 72,
                height: 72,
                child: CircularProgressIndicator(
                  color: accentCyan.withOpacity(0.3),
                  strokeWidth: 3,
                ),
              ),
              const Icon(Icons.description_outlined, color: accentCyan, size: 28),
            ],
          ),
        ),
        const SizedBox(height: 20),
        const Text(
          'Generating Your Report',
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue),
        ),
        const SizedBox(height: 8),
        const LoadingMessageCycler(),
        const SizedBox(height: 6),
        const Text(
          'This usually takes a few seconds...',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 12, color: textLight),
        ),
      ],
    );
  }

  Widget _buildSuccessState() {
    return Column(
      key: const ValueKey('success'),
      children: [
        Container(
          width: 72,
          height: 72,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [accentGreen.withOpacity(0.15), accentGreen.withOpacity(0.05)],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            shape: BoxShape.circle,
          ),
          child: const Icon(Icons.check_circle_rounded, color: accentGreen, size: 40),
        ),
        const SizedBox(height: 16),
        const Text(
          'Report Ready!',
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: accentGreen),
        ),
        const SizedBox(height: 6),
        const Text(
          'Your medical report is ready.\nDownload it or share via QR code below.',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 13, color: textLight, height: 1.4),
        ),
      ],
    );
  }

  Widget _buildErrorState(String message) {
    return Column(
      key: const ValueKey('error'),
      children: [
        Container(
          width: 72,
          height: 72,
          decoration: BoxDecoration(
            color: alertRed.withOpacity(0.08),
            shape: BoxShape.circle,
          ),
          child: const Icon(Icons.cloud_off_rounded, color: alertRed, size: 36),
        ),
        const SizedBox(height: 16),
        const Text(
          'Report Generation Failed',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: alertRed),
        ),
        const SizedBox(height: 6),
        Text(
          message,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 13, color: textLight, height: 1.4),
        ),
        const SizedBox(height: 16),
        SizedBox(
          height: 44,
          child: ElevatedButton.icon(
            onPressed: () {
              if (widget.patientId != null && widget.scanIds != null) {
                ref.read(referralProvider.notifier).submitReferral(
                  patientId: widget.patientId!,
                  scanIds: widget.scanIds!,
                );
              }
            },
            icon: const Icon(Icons.refresh_rounded, color: Colors.white, size: 18),
            label: const Text('Try Again', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
            style: ElevatedButton.styleFrom(
              backgroundColor: accentCyan,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            ),
          ),
        ),
      ],
    );
  }

  // =========================================================================
  // DOWNLOAD BUTTON
  // =========================================================================

  Widget _buildDownloadButton(String signedUrl, bool hasData, bool isLoading) {
    final enabled = hasData && signedUrl.isNotEmpty && !_isDownloading;

    return SizedBox(
      width: double.infinity,
      height: 56,
      child: ElevatedButton(
        onPressed: enabled ? () => _downloadReport(signedUrl) : null,
        style: ElevatedButton.styleFrom(
          backgroundColor: accentGreen,
          disabledBackgroundColor: textLight.withOpacity(0.15),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          elevation: enabled ? 4 : 0,
          shadowColor: accentGreen.withOpacity(0.3),
        ),
        child: _isDownloading
            ? Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: const [
                  SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)),
                  SizedBox(width: 12),
                  Text('Downloading...', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white)),
                ],
              )
            : Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.download_rounded, color: enabled ? Colors.white : Colors.white54),
                  const SizedBox(width: 12),
                  Text(
                    'Download Report (PDF)',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: enabled ? Colors.white : Colors.white54),
                  ),
                ],
              ),
      ),
    );
  }

  // =========================================================================
  // QR GENERATION BUTTON
  // =========================================================================

  Widget _buildGenerateQRButton(String signedUrl, bool hasData, bool isLoading) {
    final enabled = hasData && signedUrl.isNotEmpty;

    return SizedBox(
      width: double.infinity,
      height: 56,
      child: OutlinedButton(
        onPressed: enabled
            ? () {
                setState(() => _showQR = !_showQR);
              }
            : null,
        style: OutlinedButton.styleFrom(
          side: BorderSide(
            color: enabled ? accentCyan : textLight.withOpacity(0.2),
            width: 2,
          ),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              _showQR ? Icons.visibility_off_rounded : Icons.qr_code_2_rounded,
              color: enabled ? accentCyan : textLight.withOpacity(0.4),
            ),
            const SizedBox(width: 12),
            Text(
              _showQR ? 'Hide QR Code' : 'Generate QR Code',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
                color: enabled ? accentCyan : textLight.withOpacity(0.4),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // =========================================================================
  // QR DISPLAY CARD
  // =========================================================================

  Widget _buildQRDisplay(String signedUrl) {
    return AnimatedSize(
      duration: const Duration(milliseconds: 350),
      curve: Curves.easeInOut,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(24),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(24),
          boxShadow: [
            BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 20, offset: const Offset(0, 5)),
          ],
        ),
        child: Column(
          children: [
            const Text(
              'Scan to Access Report',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: primaryBlue),
            ),
            const SizedBox(height: 4),
            const Text(
              'Share this QR with the receiving doctor',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: textLight),
            ),
            const SizedBox(height: 24),

            // QR Code with RepaintBoundary for saving
            RepaintBoundary(
              key: _qrKey,
              child: Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: accentCyan.withOpacity(0.2), width: 2),
                ),
                child: QrImageView(
                  data: signedUrl,
                  version: QrVersions.auto,
                  size: 200.0,
                  foregroundColor: primaryBlue,
                  embeddedImage: null,
                  embeddedImageStyle: null,
                ),
              ),
            ),

            const SizedBox(height: 20),

            // Save QR button
            SizedBox(
              width: double.infinity,
              height: 48,
              child: ElevatedButton.icon(
                onPressed: _saveQrToGallery,
                icon: const Icon(Icons.save_alt_rounded, color: Colors.white, size: 20),
                label: const Text(
                  'Save QR to Gallery',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white),
                ),
                style: ElevatedButton.styleFrom(
                  backgroundColor: primaryBlue,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  elevation: 2,
                  shadowColor: primaryBlue.withOpacity(0.3),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

}

// =========================================================================
// CUSTOM LOADING CYCLER WIDGET
// =========================================================================
class LoadingMessageCycler extends StatefulWidget {
  const LoadingMessageCycler({Key? key}) : super(key: key);

  @override
  State<LoadingMessageCycler> createState() => _LoadingMessageCyclerState();
}

class _LoadingMessageCyclerState extends State<LoadingMessageCycler> {
  final List<String> _messages = [
    'Gathering findings...',
    'Generating AI summary...',
    'Assembling PDF...',
  ];
  int _currentIndex = 0;
  bool _mounted = true;

  @override
  void initState() {
    super.initState();
    _cycleMessages();
  }

  Future<void> _cycleMessages() async {
    while (_mounted) {
      await Future.delayed(const Duration(milliseconds: 2500));
      if (!_mounted) break;
      setState(() {
        _currentIndex = (_currentIndex + 1) % _messages.length;
      });
    }
  }

  @override
  void dispose() {
    _mounted = false;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 500),
      child: Text(
        _messages[_currentIndex],
        key: ValueKey<int>(_currentIndex),
        style: const TextStyle(
          color: textDark,
          fontSize: 14,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}