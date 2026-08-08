import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../chat/screens/ai_chat_screen.dart';

class TemporalSelectionScreen extends StatelessWidget {
  const TemporalSelectionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: bgLight,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, color: primaryBlue),
          onPressed: () => context.pop(),
        ),
        title: const Text('Select Modality', style: TextStyle(color: primaryBlue, fontWeight: FontWeight.bold)),
      ),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Which diagnostic modality would you like to track?',
              style: TextStyle(fontSize: 18, color: textDark, fontWeight: FontWeight.w600, height: 1.4),
            ),
            const SizedBox(height: 32),
            _buildModalityCard(
              context: context,
              title: 'Chest X-Ray',
              subtitle: 'Track pulmonary and thoracic risk over time',
              icon: Icons.monitor_heart,
              modality: 'cxr',
            ),
            const SizedBox(height: 16),
            _buildModalityCard(
              context: context,
              title: 'ECG Analysis',
              subtitle: 'Track cardiac rhythm progression',
              icon: Icons.show_chart,
              modality: 'ecg',
            ),
            const SizedBox(height: 16),
            _buildModalityCard(
              context: context,
              title: 'Skin Lesion',
              subtitle: 'Monitor dermatological changes',
              icon: Icons.center_focus_weak,
              modality: 'skin',
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildModalityCard({
    required BuildContext context,
    required String title,
    required String subtitle,
    required IconData icon,
    required String modality,
  }) {
    return GestureDetector(
      onTap: () {
        context.pushNamed('temporal_tracking', pathParameters: {'modality': modality});
      },
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(24),
          boxShadow: [
            BoxShadow(
              color: primaryBlue.withOpacity(0.05),
              blurRadius: 20,
              offset: const Offset(0, 10),
            )
          ],
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: primaryBlue.withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: Icon(icon, color: primaryBlue, size: 28),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: primaryBlue)),
                  const SizedBox(height: 4),
                  Text(subtitle, style: const TextStyle(fontSize: 13, color: textLight)),
                ],
              ),
            ),
            const Icon(Icons.arrow_forward_ios_rounded, color: textLight, size: 16),
          ],
        ),
      ),
    );
  }
}
