import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../models/fusion_models.dart';

const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color bgLight = Color(0xFFF4F8FB);

class FusionResultScreen extends StatelessWidget {
  final FusionResponse fusionData;

  const FusionResultScreen({Key? key, required this.fusionData})
      : super(key: key);

  Color _getRiskColor(String riskLevel) {
    switch (riskLevel.toUpperCase()) {
      case 'LOW':
        return const Color(0xFF00A36C); // Green
      case 'MODERATE':
        return const Color(0xFFF2994A); // Yellow
      case 'HIGH':
        return const Color(0xFFE63946); // Orange
      case 'CRITICAL':
        return const Color(0xFF8B0000); // Red
      default:
        return const Color(0xFF00A36C);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!fusionData.fusionPerformed) {
      return Scaffold(
        backgroundColor: bgLight,
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          elevation: 0,
          leading: IconButton(
            icon: const Icon(Icons.arrow_back_ios_new_rounded, color: primaryBlue),
            onPressed: () => context.pop(),
          ),
          title: const Text('Master AI Fusion',
              style: TextStyle(color: primaryBlue, fontWeight: FontWeight.bold, fontSize: 18)),
          centerTitle: true,
        ),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.auto_awesome_outlined, size: 64, color: textLight.withOpacity(0.5)),
                const SizedBox(height: 16),
                const Text('Insufficient Data',
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: textDark)),
                const SizedBox(height: 12),
                const Text(
                  'Fusion requires scans from at least two different modalities to synthesize a combined risk profile.',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 16, color: textLight, height: 1.5),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final riskColor = _getRiskColor(fusionData.riskLevel ?? 'LOW');

    return Scaffold(
      backgroundColor: bgLight,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded,
              color: primaryBlue),
          onPressed: () => context.pop(),
        ),
        title: const Text('Master AI Fusion',
            style: TextStyle(
                color: primaryBlue, fontWeight: FontWeight.bold, fontSize: 18)),
        centerTitle: true,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // CRITICAL ALERT BANNER
            if (fusionData.criticalAlert)
              Container(
                margin: const EdgeInsets.only(bottom: 24),
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFF8B0000).withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: const Color(0xFF8B0000).withOpacity(0.3)),
                ),
                child: Row(
                  children: const [
                    Icon(Icons.warning_amber_rounded, color: Color(0xFF8B0000)),
                    SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'CRITICAL ALERT: Immediate medical attention recommended based on fused findings.',
                        style: TextStyle(color: Color(0xFF8B0000), fontWeight: FontWeight.bold),
                      ),
                    ),
                  ],
                ),
              ),

            // UNSCORED BANNER
            if (fusionData.unscored.isNotEmpty)
              Container(
                margin: const EdgeInsets.only(bottom: 24),
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFFF2994A).withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: const Color(0xFFF2994A).withOpacity(0.3)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.info_outline, color: Color(0xFFE67E22)),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'Note: The following modalities were excluded from the risk score due to raw logit outputs: ${fusionData.unscored.join(", ").toUpperCase()}',
                        style: const TextStyle(color: Color(0xFFE67E22), fontWeight: FontWeight.w600, fontSize: 13),
                      ),
                    ),
                  ],
                ),
              ),

            // 1. RISK SCORE GAUGE CARD
            Container(
              padding:
                  const EdgeInsets.symmetric(vertical: 40, horizontal: 20),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(24),
                boxShadow: [
                  BoxShadow(
                      color: primaryBlue.withOpacity(0.05),
                      blurRadius: 20,
                      offset: const Offset(0, 10))
                ],
              ),
              child: Column(
                children: [
                  const Text('Overall Patient Risk Score',
                      style: TextStyle(
                          fontSize: 14,
                          color: textLight,
                          fontWeight: FontWeight.w600)),
                  const SizedBox(height: 16),
                  Stack(
                    alignment: Alignment.center,
                    children: [
                      SizedBox(
                        width: 150,
                        height: 150,
                        child: CircularProgressIndicator(
                          value: fusionData.overallRiskScore ?? 0.0,
                          strokeWidth: 12,
                          backgroundColor: riskColor.withOpacity(0.1),
                          valueColor: AlwaysStoppedAnimation<Color>(riskColor),
                        ),
                      ),
                      Column(
                        children: [
                          Text(
                            '${((fusionData.overallRiskScore ?? 0.0) * 100).toInt()}%',
                            style: TextStyle(
                                fontSize: 36,
                                fontWeight: FontWeight.bold,
                                color: riskColor),
                          ),
                          Text((fusionData.riskLevel ?? 'UNKNOWN').toUpperCase(),
                              style: TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.bold,
                                  color: riskColor)),
                        ],
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 32),

            // 2. MODALITY BREAKDOWN
            if (fusionData.modalityRisks.isNotEmpty) ...[
              const Text('Modality Breakdown',
                  style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: primaryBlue)),
              const SizedBox(height: 16),
              ...fusionData.modalityRisks.map((modality) {
                return Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: primaryBlue.withOpacity(0.05)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(modality.modality.toUpperCase(),
                              style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 16,
                                  color: textDark)),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 10, vertical: 4),
                            decoration: BoxDecoration(
                              color: primaryBlue.withOpacity(0.1),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Text(
                                '${(modality.confidence * 100).toInt()}% Confidence',
                                style: const TextStyle(
                                    fontWeight: FontWeight.bold,
                                    fontSize: 12,
                                    color: primaryBlue)),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('• ',
                              style: TextStyle(color: textLight)),
                          Expanded(
                            child: Text('${modality.aiDiagnosis} (${modality.status})',
                                style: const TextStyle(
                                    fontSize: 13, color: textLight)),
                          ),
                        ],
                      ),
                    ],
                  ),
                );
              }).toList(),
              const SizedBox(height: 32),
            ],

            // 3. CLINICAL SUMMARY
            if (fusionData.findingsSummary != null && fusionData.findingsSummary!.isNotEmpty) ...[
              const Text('Findings Summary',
                  style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: primaryBlue)),
              const SizedBox(height: 12),
              Text(
                fusionData.findingsSummary!,
                style: const TextStyle(
                    fontSize: 15, color: textDark, height: 1.6),
              ),
              const SizedBox(height: 32),
            ],
            
            // 4. CLINICAL CORRELATION
            if (fusionData.clinicalCorrelation != null && fusionData.clinicalCorrelation!.isNotEmpty) ...[
              const Text('Clinical Correlation',
                  style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: primaryBlue)),
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.04), blurRadius: 10, offset: const Offset(0, 4))],
                  border: Border.all(color: primaryBlue.withOpacity(0.05)),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.link_rounded, color: Color(0xFF00B4D8)),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Text(
                        fusionData.clinicalCorrelation!,
                        style: const TextStyle(
                            fontSize: 15, color: textDark, height: 1.6),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 32),
            ],
          ],
        ),
      ),
    );
  }
}