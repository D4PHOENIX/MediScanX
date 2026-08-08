import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'dart:ui'; // Required for ImageFilter (blur effect)
import 'package:mediscanx_mobile/features/diagnostic/providers/skin_diagnostic_provider.dart';

class SkinDiagnosticScreen extends ConsumerWidget {
  const SkinDiagnosticScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Watch the Riverpod provider state
    final skinState = ref.watch(skinDiagnosticProvider);
    final skinNotifier = ref.read(skinDiagnosticProvider.notifier);

    // Clinical Color Palette
    const primaryColor = Color(0xFF0F4C81); // Deep Clinical Blue
    const backgroundColor = Color(0xFFF4F7F6); // Soft White/Gray

    return Scaffold(
      backgroundColor: backgroundColor,
      appBar: AppBar(
        title: const Text(
          'Skin DermaScan',
          style: TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
        ),
        backgroundColor: primaryColor,
        elevation: 0,
        actions: [
          if (skinState.imageBytes != null)
            IconButton(
              icon: const Icon(Icons.refresh, color: Colors.white), // FIXED: Icons instead of Colors
              onPressed: () => skinNotifier.reset(),
            ),
        ],
      ),
      body: Stack(
        children: [
          // ==========================================
          // MAIN CONTENT LAYER
          // ==========================================
          SingleChildScrollView(
            padding: const EdgeInsets.all(20.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // 1. Image Preview Box
                Container(
                  height: 280,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(24),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withOpacity(0.05),
                        blurRadius: 15,
                        offset: const Offset(0, 5),
                      ),
                    ],
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: skinState.imageBytes != null
                      ? Image.memory(skinState.imageBytes!, fit: BoxFit.cover)
                      : Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.add_a_photo_outlined, size: 64, color: primaryColor.withOpacity(0.4)),
                      const SizedBox(height: 12),
                      Text(
                        'No Image Captured Yet',
                        style: TextStyle(color: Colors.grey[600], fontSize: 16),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),

                // 2. Action Buttons (Only show when no image is captured)
                if (skinState.imageBytes == null) ...[
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: primaryColor,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                    ),
                    icon: const Icon(Icons.camera_alt, color: Colors.white),
                    label: const Text('Capture via Camera', style: TextStyle(fontSize: 16, color: Colors.white)),
                    onPressed: () => skinNotifier.analyzeImage(ImageSource.camera),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: primaryColor),
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                    ),
                    icon: const Icon(Icons.photo_library, color: primaryColor),
                    label: const Text('Upload from Gallery', style: TextStyle(fontSize: 16, color: primaryColor)),
                    onPressed: () => skinNotifier.analyzeImage(ImageSource.gallery),
                  ),
                ],

                // 3. Error Feedback
                if (skinState.errorMessage != null) ...[
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.red[50],
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: Colors.red.shade200), // FIXED: Border.all instead of BorderSide
                    ),
                    child: Text(
                      skinState.errorMessage!,
                      style: TextStyle(color: Colors.red[900]),
                      textAlign: TextAlign.center, // FIXED: TextAlign.center instead of Center
                    ),
                  ),
                ],

                // 4. Results Section
                if (skinState.results != null) ...[
                  const Text(
                    'Diagnostic Analysis',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryColor),
                  ),
                  const SizedBox(height: 12),
                  ...() {
                    final sortedEntries = skinState.results!.entries.toList()
                      ..sort((a, b) => b.value.compareTo(a.value));
                    return sortedEntries.take(1).map((entry) {
                      final percentage = entry.value * 100;
                      return _buildResultCard(entry.key, percentage, primaryColor);
                    }).toList();
                  }(),
                ],
              ],
            ),
          ),

          // ==========================================
          // GLASSMORPHISM LOADING OVERLAY LAYER
          // ==========================================
          if (skinState.isLoading)
            Positioned.fill(
              child: BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 10.0, sigmaY: 10.0), // The Frosted Glass effect
                child: Container(
                  color: Colors.white.withOpacity(0.15), // Translucent layer
                  child: Center(
                    child: Container(
                      padding: const EdgeInsets.all(32),
                      decoration: BoxDecoration(
                        color: Colors.white.withOpacity(0.7),
                        borderRadius: BorderRadius.circular(24),
                        border: Border.all(color: Colors.white.withOpacity(0.5), width: 1.5), // FIXED: Border.all instead of BorderSide
                        boxShadow: [
                          BoxShadow(
                            color: Colors.black.withOpacity(0.1),
                            blurRadius: 30,
                            offset: const Offset(0, 10),
                          ),
                        ],
                      ),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const CircularProgressIndicator(
                            valueColor: AlwaysStoppedAnimation<Color>(primaryColor),
                            strokeWidth: 4,
                          ),
                          const SizedBox(height: 20),
                          Text(
                            'Analyzing Lesion...',
                            style: TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.bold,
                              color: primaryColor.withOpacity(0.9),
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            'Running INT8 Neural Engine',
                            style: TextStyle(fontSize: 12, color: Colors.grey[700]),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  // Helper builder for custom disease progress bars
  Widget _buildResultCard(String label, double percentage, Color mainColor) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(color: Colors.black.withOpacity(0.02), blurRadius: 10, offset: const Offset(0, 4)),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
              Text('${percentage.toStringAsFixed(1)}%', style: TextStyle(fontWeight: FontWeight.bold, color: mainColor)),
            ],
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: LinearProgressIndicator(
              value: percentage / 100,
              backgroundColor: mainColor.withOpacity(0.1),
              valueColor: AlwaysStoppedAnimation<Color>(mainColor),
              minHeight: 8,
            ),
          ),
        ],
      ),
    );
  }
}