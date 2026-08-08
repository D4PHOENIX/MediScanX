import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:mediscanx_mobile/features/dashboard/providers/temporal_provider.dart';
import 'package:mediscanx_mobile/features/dashboard/models/temporal_models.dart';
import 'package:mediscanx_mobile/features/chat/models/ai_chat_args.dart'; // NEW IMPORT

const Color primaryBlue = Color(0xFF003B5C);
const Color accentCyan = Color(0xFF00B4D8);
const Color textLight = Color(0xFF7A98A3);
const Color bgLight = Color(0xFFF4F8FB);

class TemporalTrackingScreen extends ConsumerWidget {
  final String modality;
  const TemporalTrackingScreen({Key? key, required this.modality}) : super(key: key);

  String _getTitle() {
    switch (modality) {
      case 'cxr': return 'Chest X-Ray Tracking';
      case 'ecg': return 'ECG Risk Tracking';
      case 'skin': return 'Skin Lesion Tracking';
      default: return 'Temporal Risk Tracking';
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final trendsAsync = ref.watch(patientTrendsProvider(modality));
    final historyAsync = ref.watch(patientHistoryProvider(modality));

    return Scaffold(
      backgroundColor: bgLight,
      appBar: AppBar(
        backgroundColor: bgLight,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, color: primaryBlue),
          onPressed: () => context.pop(),
        ),
        title: Text(_getTitle(), style: const TextStyle(color: primaryBlue, fontWeight: FontWeight.bold)),
      ),
      body: trendsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator(color: accentCyan)),
        error: (err, stack) => Center(child: Text('Error: $err')),
        data: (trendData) {
          if (trendData == null || trendData.dataPoints == 0) {
            return _buildEmptyState();
          }

          return historyAsync.when(
            loading: () => const Center(child: CircularProgressIndicator(color: accentCyan)),
            error: (err, stack) => Center(child: Text('Error: $err')),
            data: (historyData) {
              if (historyData == null || historyData.items.isEmpty) {
                return _buildEmptyState();
              }

              return SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _buildSummaryCard(trendData),
                    const SizedBox(height: 32),
                    const Text('Risk Trajectory', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
                    const SizedBox(height: 16),
                    _buildChartCard(historyData.items),
                    const SizedBox(height: 32),
                    const Text('Scan History', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
                    const SizedBox(height: 16),
                    _buildHistoryList(historyData.items),
                  ],
                ),
              );
            },
          );
        },
      ),
      floatingActionButton: historyAsync.whenOrNull(
        data: (historyData) {
          if (historyData == null || historyData.items.isEmpty) return null;
          
          return FloatingActionButton.extended(
            backgroundColor: primaryBlue,
            onPressed: () {
              final mostRecentScanId = historyData.items.first.scanId;
              context.pushNamed('ai_chat', extra: AIChatArgs(
                scanContextId: mostRecentScanId,
                initialPrompt: 'What changed since my last scan?',
              ));
            },
            icon: const Icon(Icons.auto_awesome, color: Colors.white),
            label: const Text('Ask AI about my trend', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
          );
        },
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: const [
          Icon(Icons.show_chart_rounded, size: 64, color: textLight),
          SizedBox(height: 16),
          Text('No tracking data available', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: primaryBlue)),
          SizedBox(height: 8),
          Text('Complete more scans to see your temporal risk trend.', style: TextStyle(color: textLight)),
        ],
      ),
    );
  }

  Widget _buildSummaryCard(TrendAnalysis trend) {
    Color trendColor = const Color(0xFF00A36C);
    IconData trendIcon = Icons.trending_flat;
    String trendText = 'Stable';

    if (trend.trend == 'WORSENING') {
      trendColor = Colors.redAccent;
      trendIcon = Icons.trending_up;
      trendText = 'Risk Increasing';
    } else if (trend.trend == 'IMPROVING') {
      trendColor = const Color(0xFF00A36C);
      trendIcon = Icons.trending_down;
      trendText = 'Risk Decreasing';
    } else if (trend.trend == 'UNCHANGED' || trend.trend == 'STABLE') {
      trendColor = const Color(0xFF00A36C);
      trendIcon = Icons.trending_flat;
      trendText = 'Risk Stable';
    } else if (trend.trend == 'CHANGED') {
      trendColor = Colors.orange;
      trendIcon = Icons.swap_horiz;
      if (trend.fromDiagnosis != null && trend.toDiagnosis != null) {
        trendText = '${trend.fromDiagnosis} ➡️ ${trend.toDiagnosis}';
      } else {
        trendText = 'Condition Changed';
      }
    } else if (trend.trend == 'INDETERMINATE') {
      trendColor = textLight;
      trendIcon = Icons.help_outline;
      trendText = 'Trend Indeterminate';
    } else if (trend.trend == 'INSUFFICIENT_DATA') {
      trendColor = textLight;
      trendIcon = Icons.hourglass_empty;
      trendText = 'Insufficient Data';
    }

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 15, offset: const Offset(0, 5))],
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: trendColor.withOpacity(0.1), shape: BoxShape.circle),
            child: Icon(trendIcon, color: trendColor, size: 32),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(trendText, style: TextStyle(color: trendColor, fontSize: 18, fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text('Based on ${trend.dataPoints} previous scans', style: const TextStyle(color: textLight, fontSize: 13)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildChartCard(List<PatientHistoryScan> scans) {
    // Sort scans by date ascending
    final sortedScans = List<PatientHistoryScan>.from(scans)
      ..sort((a, b) => a.scanDate.compareTo(b.scanDate));

    List<FlSpot> spots = [];
    
    for (int i = 0; i < sortedScans.length; i++) {
      // 0 = Normal, 1 = Warning (Moderate), 2 = High Risk
      double severity = sortedScans[i].scanStatus.toDouble();
      spots.add(FlSpot(i.toDouble(), severity));
    }

    // Calculate dynamic width to allow scrolling if there are many scans
    // Assume we want at least 40 pixels per scan point.
    // If the total width is less than the screen width, it will just fill the screen.
    return LayoutBuilder(
      builder: (context, constraints) {
        double minWidth = constraints.maxWidth;
        double calculatedWidth = sortedScans.length * 40.0;
        double finalWidth = calculatedWidth > minWidth ? calculatedWidth : minWidth;

        return Container(
          height: 250,
          padding: const EdgeInsets.only(top: 20, right: 0, bottom: 20, left: 0),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(20),
            boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 15, offset: const Offset(0, 5))],
          ),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            physics: const BouncingScrollPhysics(),
            child: Container(
              width: finalWidth,
              padding: const EdgeInsets.only(right: 20, left: 10),
              child: LineChart(
                LineChartData(
                  gridData: FlGridData(
                    show: true, 
                    drawVerticalLine: false,
                    horizontalInterval: 1,
                    getDrawingHorizontalLine: (value) => FlLine(color: Colors.grey.withOpacity(0.2), strokeWidth: 1),
                  ),
                  titlesData: FlTitlesData(
                    show: true,
                    rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    leftTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        interval: 1,
                        reservedSize: 60,
                        getTitlesWidget: (value, meta) {
                          if (value != value.toInt()) return const SizedBox();
                          String text;
                          switch (value.toInt()) {
                            case 0: text = 'Normal'; break;
                            case 1: text = 'Warning'; break;
                            case 2: text = 'High Risk'; break;
                            default: return const SizedBox();
                          }
                          return Padding(
                            padding: const EdgeInsets.only(right: 8.0),
                            child: Text(text, textAlign: TextAlign.right, style: const TextStyle(color: textLight, fontSize: 10, fontWeight: FontWeight.bold)),
                          );
                        },
                      ),
                    ),
                    bottomTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        interval: 1,
                        getTitlesWidget: (value, meta) {
                          if (value != value.toInt() || value < 0 || value >= sortedScans.length) return const SizedBox();
                          
                          // Since we now scroll, we don't need to aggressively cull the labels.
                          // We can show every date, or maybe every other date if it's super dense.
                          // 40px per point is enough to show most dates.
                          
                          final date = sortedScans[value.toInt()].scanDate;
                          final months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                          return Padding(
                            padding: const EdgeInsets.only(top: 8.0),
                            child: Text('${months[date.month - 1]} ${date.day}', style: const TextStyle(color: textLight, fontSize: 10)),
                          );
                        },
                      ),
                    ),
                  ),
                  borderData: FlBorderData(show: false),
                  minX: 0,
                  maxX: (sortedScans.length - 1).toDouble(),
                  minY: -0.2, // Padding below 0
                  maxY: 2.2,  // Padding above 2
                  lineBarsData: [
                    LineChartBarData(
                      spots: spots,
                      isCurved: false, // Medically accurate: no interpolation
                      color: textLight.withOpacity(0.5),
                      barWidth: 2,
                      dashArray: [5, 5], // Dotted line sequence
                      isStrokeCapRound: true,
                      dotData: FlDotData(
                        show: true,
                        getDotPainter: (spot, percent, barData, index) {
                          Color dotColor;
                          if (spot.y == 2) dotColor = Colors.redAccent;
                          else if (spot.y == 1) dotColor = Colors.orange;
                          else dotColor = const Color(0xFF00A36C);
                          
                          // We can keep the dots reasonably sized since there's room now
                          double radius = 4;
                          
                          return FlDotCirclePainter(
                            radius: radius,
                            color: dotColor,
                            strokeWidth: 2,
                            strokeColor: Colors.white,
                          );
                        }
                      ),
                      belowBarData: BarAreaData(show: false), // No fill
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      }
    );
  }

  Widget _buildHistoryList(List<PatientHistoryScan> scans) {
    return ListView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      itemCount: scans.length,
      itemBuilder: (context, index) {
        final scan = scans[index];
        
        String riskText;
        Color riskColor;
        Color bgRiskColor;
        
        if (scan.scanStatus == 2) {
          riskText = 'HIGH RISK';
          riskColor = const Color(0xFFE63946);
          bgRiskColor = const Color(0xFFFFEAEA);
        } else if (scan.scanStatus == 1) {
          riskText = 'WARNING';
          riskColor = const Color(0xFFF2994A);
          bgRiskColor = const Color(0xFFFDF0E3);
        } else {
          riskText = 'Normal';
          riskColor = const Color(0xFF00A36C);
          bgRiskColor = const Color(0xFFEAF8FC);
        }
        
        String niceModality = scan.scanType.toUpperCase();
        if (scan.scanType == 'cxr') niceModality = 'Chest X-Ray';
        else if (scan.scanType == 'ecg') niceModality = 'ECG';
        else if (scan.scanType == 'skin') niceModality = 'Skin Lesion';

        final months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        final dateStr = '${months[scan.scanDate.month - 1]} ${scan.scanDate.day}, ${scan.scanDate.year}';

        return Card(
          elevation: 0,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          margin: const EdgeInsets.only(bottom: 12),
          child: ListTile(
            leading: CircleAvatar(
              backgroundColor: bgRiskColor,
              child: Icon(
                scan.scanType == 'cxr' ? Icons.monitor_heart : (scan.scanType == 'ecg' ? Icons.show_chart : Icons.center_focus_weak),
                color: riskColor,
              ),
            ),
            title: Text(scan.aiDiagnosis, style: const TextStyle(fontWeight: FontWeight.bold, color: primaryBlue)),
            subtitle: Text('$niceModality • ${(scan.confidence * 100).clamp(0, 100).toStringAsFixed(1)}% confidence'),
            trailing: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(riskText, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 10, color: riskColor)),
                Text(dateStr, style: const TextStyle(fontSize: 10, color: textLight)),
                Text('${(scan.scanDate.toLocal().hour % 12 == 0 ? 12 : scan.scanDate.toLocal().hour % 12)}:${scan.scanDate.toLocal().minute.toString().padLeft(2, '0')} ${scan.scanDate.toLocal().hour >= 12 ? 'PM' : 'AM'}', style: const TextStyle(fontSize: 9, color: textLight)),
              ],
            ),
          ),
        );
      },
    );
  }
}
