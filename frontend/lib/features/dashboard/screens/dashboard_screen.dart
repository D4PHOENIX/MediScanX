// lib/features/dashboard/screens/dashboard_screen.dart
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:drift/drift.dart' as drift;
import '../../auth/providers/auth_state_provider.dart';
import '../../auth/providers/database_provider.dart';

// Import the Diagnostic Screen to access the routing provider
import 'package:mediscanx_mobile/features/diagnostic/screens/diagnostic_screen.dart';
import 'package:mediscanx_mobile/core/utils/error_helper.dart'; // NEW IMPORT

// --- NEW FUSION IMPORTS ---
import 'package:mediscanx_mobile/features/auth/providers/database_provider.dart';
import 'package:mediscanx_mobile/core/config/drift_database.dart';
import 'package:mediscanx_mobile/features/dashboard/services/doctor_patient_profile_service.dart';
import 'package:mediscanx_mobile/features/diagnostic/providers/fusion_provider.dart';
import 'package:mediscanx_mobile/features/diagnostic/models/fusion_models.dart';
import 'package:mediscanx_mobile/features/diagnostic/services/scan_dao.dart';
import 'package:mediscanx_mobile/features/dashboard/providers/temporal_provider.dart';
import 'dart:convert';

import 'package:mediscanx_mobile/features/diagnostic/providers/scan_history_provider.dart';
import 'package:mediscanx_mobile/features/referral/services/referral_service.dart';


const Color primaryBlue = Color(0xFF003B5C);
const Color textDark = Color(0xFF002D40);
const Color textLight = Color(0xFF7A98A3);
const Color accentCyan = Color(0xFF00B4D8);
const Color bgLight = Color(0xFFF4F8FB);

// Enum defined safely outside the class
enum DiagnosticStatus { normal, alert, pending }

// ==========================================
// OFFLINE-FIRST PROFILE PROVIDER (UNTOUCHED)
// ==========================================

final doctorHasPatientProfileProvider = FutureProvider.family<bool, String>((ref, userId) async {
  final service = ref.watch(doctorPatientProfileServiceProvider);
  return await service.hasPatientProfile(userId);
});

final profileProvider = StreamProvider.family<Map<String, dynamic>?, String>((ref, userId) async* {
  final appDb = ref.watch(databaseProvider);

  if (userId == 'ID-PENDING') {
    yield null;
    return;
  }

  // 1. Get the role from Supabase metadata (we saved this during registration!)
  final user = Supabase.instance.client.auth.currentUser;

  String _calculateAgeLabel(String? dateOfBirthRaw) {
    if (dateOfBirthRaw == null || dateOfBirthRaw.trim().isEmpty) return '--';
    final dob = DateTime.tryParse(dateOfBirthRaw);
    if (dob == null) return '--';

    final now = DateTime.now();
    var age = now.year - dob.year;
    if (now.month < dob.month || (now.month == dob.month && now.day < dob.day)) {
      age--;
    }
    return age < 0 ? '--' : age.toString();
  }

  Map<String, dynamic>? metadataFallback() {
    final metadata = user?.userMetadata ?? const <String, dynamic>{};
    final metaRole =
    (metadata['role'] ?? metadata['userType'])?.toString().toLowerCase();
    final dobRaw = (metadata['date_of_birth'] ?? metadata['dateOfBirth'])
        ?.toString();
    return {
      'fullName': (metadata['full_name'] ?? metadata['fullName'])?.toString() ??
          'Guest User',
      'username': metadata['username']?.toString(),
      'email': user?.email ?? '--',
      'phone': (metadata['phone_number'] ?? metadata['phone'])?.toString() ??
          '--',
      'gender': metadata['gender']?.toString() ?? 'Unknown',
      'dateOfBirth': dobRaw,
      'age': _calculateAgeLabel(dobRaw),
      'userType': metaRole == 'doctor' ? 'Doctor' : 'Patient',
    };
  }

  final metadataRole =
  (user?.userMetadata?['role'] ?? user?.userMetadata?['userType'])
      ?.toString()
      .toLowerCase();
  final role = metadataRole == 'doctor' ? 'Doctor' : 'Patient';

  Map<String, dynamic> rowToProfile(Map<String, Object?> row, String userType) {
    final dobRaw = row['date_of_birth']?.toString();
    return {
      'fullName': row['full_name']?.toString() ?? 'Guest User',
      'username': row['username']?.toString(),
      'email': row['email']?.toString() ?? '--',
      'phone': row['phone_number']?.toString() ?? '--',
      'gender': row['gender']?.toString() ?? 'Unknown',
      'dateOfBirth': dobRaw,
      'age': _calculateAgeLabel(dobRaw),
      'userType': userType,
    };
  }

  Future<Map<String, dynamic>?> getProfileFromTable(
      String table, String userType) async {
    final result = await appDb.customSelect(
      'SELECT full_name, username, email, phone_number, gender, date_of_birth FROM '
          '$table WHERE user_id = ?',
      variables: [drift.Variable.withString(userId)],
    ).get();

    if (result.isEmpty) return null;
    return rowToProfile(result.first.data, userType);
  }

  // 2. Watch the CORRECT table based on their role
  if (role == 'Doctor') {
    final doctorStream = appDb
        .customSelect(
      'SELECT full_name, username, email, phone_number, gender, date_of_birth '
          'FROM doctor_profiles WHERE user_id = ?',
      variables: [drift.Variable.withString(userId)],
      readsFrom: {appDb.doctorProfiles},
    )
        .watch();

    await for (final rows in doctorStream) {
      if (rows.isNotEmpty) {
        yield rowToProfile(rows.first.data, 'Doctor');
      } else {
        // Fallback when role metadata is wrong or doctor row is not downloaded yet.
        final patientProfile =
        await getProfileFromTable('patient_records', 'Patient');
        if (patientProfile != null) {
          yield patientProfile;
        } else {
          yield metadataFallback();
        }
      }
    }
  } else {
    final patientStream = appDb
        .customSelect(
      'SELECT full_name, username, email, phone_number, gender, date_of_birth '
          'FROM patient_records WHERE user_id = ?',
      variables: [drift.Variable.withString(userId)],
      readsFrom: {appDb.patientRecords},
    )
        .watch();

    await for (final rows in patientStream) {
      if (rows.isNotEmpty) {
        yield rowToProfile(rows.first.data, 'Patient');
      } else {
        // Fallback when role metadata is wrong or patient row is not downloaded yet.
        final doctorProfile =
        await getProfileFromTable('doctor_profiles', 'Doctor');
        if (doctorProfile != null) {
          yield doctorProfile;
        } else {
          yield metadataFallback();
        }
      }
    }
  }
});

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authStateProvider);

    return authState.when(
      loading: () => const Scaffold(
        body: Center(child: CircularProgressIndicator(color: accentCyan)),
      ),
      error: (error, stack) => Scaffold(
        body: Center(child: Text('Error loading user data: $error')),
      ),
      data: (user) {
        final currentSupabaseUser = Supabase.instance.client.auth.currentUser;
        final String userId = currentSupabaseUser?.id ?? 'ID-PENDING';
        final metadataRole =
        (currentSupabaseUser?.userMetadata?['role'] ??
            currentSupabaseUser?.userMetadata?['userType'])
            ?.toString()
            .toLowerCase();
        final String baseUserType =
        metadataRole == 'doctor' ? 'Doctor' : (user?.userType ?? 'Patient');

        final profileAsync = ref.watch(profileProvider(userId));

        return profileAsync.when(
          loading: () => const Scaffold(
            backgroundColor: bgLight,
            body: Center(child: CircularProgressIndicator(color: accentCyan)),
          ),
          error: (error, stack) => Scaffold(
            backgroundColor: bgLight,
            body: Center(child: Text('Error loading profile database: $error')),
          ),
          data: (profileData) {
            final String userName = profileData?['fullName'] ?? user?.fullName ?? 'Guest User';
            final String displayUsername = profileData?['username'] != null ? '@${profileData!['username']}' : 'ID-PENDING';
            final String gender = profileData?['gender'] ?? user?.gender ?? 'Unknown';
            final String age = profileData?['age'] ?? user?.age?.toString() ?? '--';
            final String userType = profileData?['userType'] ?? baseUserType;
            final bool isDoctor = userType.toLowerCase() == 'doctor';

            return Scaffold(
              backgroundColor: bgLight,
              drawer: _buildDrawer(context, profileData, userName, displayUsername, userType),
              body: Builder(
                builder: (innerContext) => Stack(
                  children: [
                    Positioned(
                      top: 150, right: -80,
                      child: Opacity(
                        opacity: 0.04,
                        child: Image.asset('assets/images/lungs_watermark.png', width: 400,
                          errorBuilder: (context, error, stackTrace) => const Icon(Icons.masks_outlined, size: 400, color: primaryBlue),
                        ),
                      ),
                    ),
                    SafeArea(
                      child: SingleChildScrollView(
                        padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 16.0),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _buildHeader(innerContext),
                            const SizedBox(height: 24),
                            _buildUserCard(innerContext, ref, userId, userName, displayUsername, gender, age, userType),

                            const SizedBox(height: 32),
                            Row(
                              children: [
                                const Text('Diagnostic Modules', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
                                const SizedBox(width: 8),
                                Container(
                                  padding: const EdgeInsets.all(6),
                                  decoration: const BoxDecoration(color: primaryBlue, shape: BoxShape.circle),
                                  child: const Text('3', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold)),
                                ),
                              ],
                            ),
                            const SizedBox(height: 16),
                            _buildLargeDiagnosticCard(
                              title: 'Chest X-Ray',
                              subtitle: 'Pulmonary & thoracic screening',
                              status: DiagnosticStatus.alert,
                              timeAgo: '15m ago',
                              icon: Icons.monitor_heart,
                              onTap: () {
                                // Set state to 0 before navigating
                                ref.read(diagnosticModuleIndexProvider.notifier).state = 0;
                                innerContext.goNamed('diagnostic');
                              },
                            ),
                            const SizedBox(height: 16),
                            Row(
                              children: [
                                Expanded(
                                  child: _buildSmallDiagnosticCard(
                                    title: 'ECG Analysis',
                                    subtitle: 'Cardiac rhythm & ST...',
                                    status: DiagnosticStatus.normal,
                                    timeAgo: '2h ago',
                                    icon: Icons.show_chart,
                                    onTap: () {
                                      // Set state to 1 before navigating
                                      ref.read(diagnosticModuleIndexProvider.notifier).state = 1;
                                      innerContext.goNamed('diagnostic');
                                    },
                                  ),
                                ),
                                const SizedBox(width: 16),
                                Expanded(
                                  child: _buildSmallDiagnosticCard(
                                    title: 'Skin Lesion',
                                    subtitle: 'Dermoscopic AI clas...',
                                    status: DiagnosticStatus.pending,
                                    timeAgo: '1d ago',
                                    icon: Icons.center_focus_weak,
                                    onTap: () {
                                      // Set state to 2 before navigating
                                      ref.read(diagnosticModuleIndexProvider.notifier).state = 2;
                                      innerContext.goNamed('diagnostic');
                                    },
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 24),

                            // ==========================================
                            // MASTER FUSION CARD
                            // ==========================================
                            _buildMasterFusionCard(innerContext, ref, userId),
                            const SizedBox(height: 24),

                            // ==========================================
                            // TEMPORAL TRACKING CARD
                            // ==========================================
                            _buildTemporalTrackingCard(innerContext, ref, userId),
                            const SizedBox(height: 24),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              bottomNavigationBar: _buildBottomNav(context, isDoctor),
            );
          },
        );
      },
    );
  }

  // ==========================================
  // UI COMPONENTS
  // ==========================================

  Widget _buildMasterFusionCard(BuildContext context, WidgetRef ref, String userId) {
    return GestureDetector(
      onTap: () async {
        try {
          // 1. Show Loading Spinner
          showDialog(
            context: context,
            barrierDismissible: false,
            builder: (ctx) => const Center(child: CircularProgressIndicator(color: accentCyan)),
          );

          // 2. Fetch the Patient's raw scans from the database
          final db = ref.read(databaseProvider);
          final scanDao = ScanDao(db);
          final cxrScan = await scanDao.getLatestScanByType(0, userId); // 0 = CXR
          final ecgScan = await scanDao.getLatestScanByType(1, userId); // 1 = ECG
          final skinScan = await scanDao.getLatestScanByType(2, userId); // 2 = Skin

          final scans = [cxrScan, ecgScan, skinScan].where((s) => s != null).toList();
          
          debugPrint('📋 Fusion Check: Found ${scans.length} scans. CXR=${cxrScan?.id}, ECG=${ecgScan?.id}, Skin=${skinScan?.id}');

          if (scans.length < 2) {
            if (context.mounted) {
              Navigator.of(context).pop(); // Close Spinner
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('At least two diagnostic scans (CXR, ECG, or Skin) are required for Master Fusion.'),
                  backgroundColor: Colors.orange,
                ),
              );
            }
            return;
          }

          // 3. Map into the format expected by the backend
          List<String> selectedScanIds = [];
          if (cxrScan != null) selectedScanIds.add(cxrScan.id);
          if (ecgScan != null) selectedScanIds.add(ecgScan.id);
          if (skinScan != null) selectedScanIds.add(skinScan.id);

          // 4. Hit the Python Backend
          await ref.read(fusionProvider.notifier).triggerFusion(
            selectedScanIds: selectedScanIds,
          );

          // 5. Close Spinner
          if (context.mounted) Navigator.of(context).pop();

          // 6. Navigate to the new screen if successful
          final state = ref.read(fusionProvider);
          state.when(
            data: (response) {
              if (response != null && context.mounted) {
                context.pushNamed('fusion_result', extra: response);
              }
            },
            error: (err, stack) {
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(ErrorHelper.getHumanReadableError(err)), backgroundColor: Colors.red),
                );
              }
            },
            loading: () {},
          );
        } catch (e) {
          if (context.mounted) {
            Navigator.of(context).pop(); // Close Spinner
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text(ErrorHelper.getHumanReadableError(e)), backgroundColor: Colors.red),
            );
          }
        }
      },
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            colors: [Color(0xFF003B5C), Color(0xFF005C7A)], // Deep primary gradients
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          borderRadius: BorderRadius.circular(24),
          boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.2), blurRadius: 15, offset: const Offset(0, 8))],
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Colors.white.withOpacity(0.1), shape: BoxShape.circle),
              child: const Icon(Icons.hub_rounded, color: accentCyan, size: 32),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: const [
                  Text('Master AI Fusion', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
                  SizedBox(height: 4),
                  Text('Synthesize multiple diagnostic scans into a single risk score.', style: TextStyle(color: Colors.white70, fontSize: 12)),
                ],
              ),
            ),
            const Icon(Icons.arrow_forward_ios_rounded, color: Colors.white54, size: 16),
          ],
        ),
      ),
    );
  }

  Widget _buildTemporalTrackingCard(BuildContext context, WidgetRef ref, String userId) {
    // We don't watch the trend provider here anymore since the dashboard
    // just has a generic entry point now.
    
    return GestureDetector(
      onTap: () {
        context.pushNamed('temporal_selection');
      },
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(24),
          border: Border.all(color: const Color(0xFFEAF8FC), width: 2),
          boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.04), blurRadius: 10, offset: const Offset(0, 4))],
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(12),
              decoration: const BoxDecoration(color: Color(0xFFEAF8FC), shape: BoxShape.circle),
              child: const Icon(Icons.show_chart_rounded, color: accentCyan, size: 28),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: const [
                  Text('Temporal Risk Tracking', style: TextStyle(color: primaryBlue, fontSize: 16, fontWeight: FontWeight.bold)),
                  SizedBox(height: 4),
                  Text('Monitor progression by modality', style: TextStyle(color: textLight, fontSize: 12)),
                ],
              ),
            ),
            const Icon(Icons.arrow_forward_ios_rounded, color: textLight, size: 16),
          ],
        ),
      ),
    );
  }

  Widget _buildHistoryModal(BuildContext context, WidgetRef ref, String userId) {
    // 🔴 Use the instant local SQLite stream provider instead of the Cloud API provider!
    final historyAsync = ref.watch(userScanHistoryProvider(userId));
    List<String> selectedScanIds = [];
    bool isGenerating = false;

    return StatefulBuilder(
      builder: (BuildContext context, StateSetter setState) {
        return Container(
          height: MediaQuery.of(context).size.height * 0.7,
          decoration: const BoxDecoration(
            color: bgLight,
            borderRadius: BorderRadius.only(topLeft: Radius.circular(32), topRight: Radius.circular(32)),
          ),
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Patient Scan History', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: primaryBlue)),
                  IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
                ],
              ),
              const SizedBox(height: 16),
              Expanded(
                child: historyAsync.when(
                  data: (history) {
                    if (history == null || history.isEmpty) {
                      return const Center(child: Text('No historical scans found.', style: TextStyle(color: textLight)));
                    }
                    return RefreshIndicator(
                      color: accentCyan,
                      onRefresh: () async {
                        ref.invalidate(userScanHistoryProvider(userId));
                      },
                      child: ListView.builder(
                        physics: const AlwaysScrollableScrollPhysics(),
                        itemCount: history.length,
                        itemBuilder: (context, index) {
                          final scan = history[index];
                          final isSelected = selectedScanIds.contains(scan.id);
                          
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
                          
                          return Card(
                            elevation: 0,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16),
                              side: isSelected ? const BorderSide(color: accentCyan, width: 2) : BorderSide.none,
                            ),
                            margin: const EdgeInsets.only(bottom: 12),
                            child: ListTile(
                              onTap: () {
                                setState(() {
                                  if (isSelected) {
                                    selectedScanIds.remove(scan.id);
                                  } else {
                                    selectedScanIds.add(scan.id);
                                  }
                                });
                              },
                              leading: Checkbox(
                                value: isSelected,
                                onChanged: (val) {
                                  setState(() {
                                    if (val == true) {
                                      selectedScanIds.add(scan.id);
                                    } else {
                                      selectedScanIds.remove(scan.id);
                                    }
                                  });
                                },
                                activeColor: accentCyan,
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
                              ),
                              title: Text(scan.tags.isNotEmpty ? scan.tags.first : 'Analyzed', style: const TextStyle(fontWeight: FontWeight.bold, color: primaryBlue)),
                              subtitle: Text('${scan.scanType} • ${(scan.overallConfidence * 100).toStringAsFixed(1)}% confidence'),
                              trailing: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Text(riskText, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 10, color: riskColor)),
                                  Text('${scan.scanDate.toLocal().day}/${scan.scanDate.toLocal().month}/${scan.scanDate.toLocal().year}', style: const TextStyle(fontSize: 10, color: textLight)),
                                  Text('${(scan.scanDate.toLocal().hour % 12 == 0 ? 12 : scan.scanDate.toLocal().hour % 12)}:${scan.scanDate.toLocal().minute.toString().padLeft(2, '0')} ${scan.scanDate.toLocal().hour >= 12 ? 'PM' : 'AM'}', style: const TextStyle(fontSize: 9, color: textLight)),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                    );
                  },
                  loading: () => const Center(child: CircularProgressIndicator()),
                  error: (err, stack) => Center(child: Text('Error: $err')),
                ),
              ),
              if (selectedScanIds.isNotEmpty) ...[
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: primaryBlue,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                      elevation: 0,
                    ),
                    onPressed: isGenerating
                        ? null
                        : () async {
                            setState(() => isGenerating = true);
                            try {
                              final service = ReferralService();
                              final response = await service.generateReferral(
                                patientId: userId,
                                scanIds: selectedScanIds,
                              );
                              setState(() => isGenerating = false);
                              if (context.mounted) {
                                if (response != null) {
                                  Navigator.pop(context); // Close the bottom sheet
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    const SnackBar(
                                      content: Text('Report generated successfully! Check Cloud Reports.'),
                                      backgroundColor: Colors.teal,
                                    ),
                                  );
                                } else {
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    const SnackBar(
                                      content: Text('Failed to generate report.'),
                                      backgroundColor: Colors.red,
                                    ),
                                  );
                                }
                              }
                            } catch (e) {
                              setState(() => isGenerating = false);
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(
                                    content: Text(e.toString().replaceAll('Exception: ', '')),
                                    backgroundColor: Colors.red,
                                  ),
                                );
                              }
                            }
                        },
                    child: isGenerating
                        ? Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: const [
                              SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)),
                              SizedBox(width: 12),
                              Text('Synthesizing AI Summary...', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
                            ],
                          )
                        : Text('Generate Report (${selectedScanIds.length})', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
                  ),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _buildDrawer(BuildContext context, Map<String, dynamic>? profileData, String name, String username, String role) {
    final String email = profileData?['email'] ?? 'No email provided';
    final String phone = profileData?['phone'] ?? 'No phone provided';
    String initials = "U";
    if (name.trim().isNotEmpty) initials = name.trim().split(' ').take(2).map((e) => e.isNotEmpty ? e[0] : '').join().toUpperCase();

    return Drawer(
      backgroundColor: bgLight,
      child: Column(
        children: [
          UserAccountsDrawerHeader(
            decoration: const BoxDecoration(color: primaryBlue),
            accountName: Text(name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            accountEmail: Text(username, style: TextStyle(color: Colors.white.withOpacity(0.8))),
            currentAccountPicture: CircleAvatar(backgroundColor: Colors.white, child: Text(initials, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: primaryBlue))),
          ),
          const SizedBox(height: 8),
          ListTile(leading: const Icon(Icons.email_outlined, color: primaryBlue), title: const Text('Email Address', style: TextStyle(color: textLight, fontSize: 12)), subtitle: Text(email, style: const TextStyle(color: textDark, fontWeight: FontWeight.w500, fontSize: 14))),
          ListTile(leading: const Icon(Icons.phone_outlined, color: primaryBlue), title: const Text('Phone Number', style: TextStyle(color: textLight, fontSize: 12)), subtitle: Text(phone, style: const TextStyle(color: textDark, fontWeight: FontWeight.w500, fontSize: 14))),
          ListTile(leading: const Icon(Icons.badge_outlined, color: primaryBlue), title: const Text('Account Role', style: TextStyle(color: textLight, fontSize: 12)), subtitle: Text(role[0].toUpperCase() + role.substring(1), style: const TextStyle(color: textDark, fontWeight: FontWeight.w500, fontSize: 14))),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.download_rounded, color: primaryBlue),
            title: const Text('Downloads', style: TextStyle(color: textDark, fontWeight: FontWeight.w600, fontSize: 14)),
            subtitle: const Text('View saved reports and QR codes', style: TextStyle(color: textLight, fontSize: 12)),
            onTap: () {
              Navigator.pop(context);
              context.pushNamed('downloads');
            },
          ),
          ListTile(
            leading: const Icon(Icons.bug_report_outlined, color: primaryBlue),
            title: const Text('Sync Debug', style: TextStyle(color: textDark, fontWeight: FontWeight.w600, fontSize: 14)),
            subtitle: const Text('Auth metadata + local profile + PowerSync status', style: TextStyle(color: textLight, fontSize: 12)),
            onTap: () {
              Navigator.pop(context);
              context.goNamed('sync_debug');
            },
          ),
          const Spacer(),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.logout_rounded, color: Colors.redAccent),
            title: const Text('Logout', style: TextStyle(color: Colors.redAccent, fontWeight: FontWeight.bold, fontSize: 16)),
            onTap: () {
              showDialog(
                context: context,
                builder: (BuildContext context) {
                  return AlertDialog(
                    backgroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                    title: Row(
                      children: const [
                        Icon(Icons.warning_amber_rounded, color: Colors.redAccent),
                        SizedBox(width: 8),
                        Text('Confirm Logout', style: TextStyle(color: primaryBlue, fontWeight: FontWeight.bold, fontSize: 20)),
                      ],
                    ),
                    content: const Text('Are you sure you want to log out of your account?', style: TextStyle(color: textDark, fontSize: 15)),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel', style: TextStyle(color: textLight, fontWeight: FontWeight.bold, fontSize: 16))),
                      ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: Colors.redAccent, elevation: 0, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
                        onPressed: () async {
                          Navigator.pop(context);
                          Navigator.pop(context);
                          await Supabase.instance.client.auth.signOut();
                        },
                        child: const Text('Logout', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                      ),
                    ],
                  );
                },
              );
            },
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Expanded(
          child: Row(
            children: [
              IconButton(icon: const Icon(Icons.menu_rounded, color: primaryBlue, size: 30), padding: EdgeInsets.zero, constraints: const BoxConstraints(), onPressed: () => Scaffold.of(context).openDrawer()),
              const SizedBox(width: 16),
              Image.asset('assets/images/logo_icon.png', height: 36, width: 36,
                  errorBuilder: (context, error, stackTrace) => Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: primaryBlue, borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.add_box, color: Colors.white, size: 20))),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      Text('MediScanX', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: primaryBlue)),
                      Text('AI-Powered Triage Platform', style: TextStyle(fontSize: 12, color: textLight), overflow: TextOverflow.ellipsis)
                    ]
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(color: const Color(0xFFE6F7F0), borderRadius: BorderRadius.circular(20), border: Border.all(color: const Color(0xFFB3E6D0))),
          child: Row(children: const [Icon(Icons.wifi, size: 12, color: Color(0xFF00A36C)), SizedBox(width: 4), Text('Offline-First', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: Color(0xFF00A36C)))]),
        ),
      ],
    );
  }

  Widget _buildUserCard(BuildContext context, WidgetRef ref, String userId, String name, String id, String gender, String age, String role) {
    String initials = "U";
    if (name.trim().isNotEmpty) initials = name.trim().split(' ').take(2).map((e) => e.isNotEmpty ? e[0] : '').join().toUpperCase();

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(24), boxShadow: [BoxShadow(color: primaryBlue.withOpacity(0.05), blurRadius: 20, spreadRadius: 5, offset: const Offset(0, 5))]),
      child: Column(
        children: [
          Row(
            children: [
              CircleAvatar(radius: 24, backgroundColor: primaryBlue, child: Text(initials, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold))),
              const SizedBox(width: 16),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: textDark)), Text(id, style: const TextStyle(fontSize: 13, color: textLight))])),
              Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6), decoration: BoxDecoration(color: const Color(0xFFE6F7F0), borderRadius: BorderRadius.circular(20)), child: Row(children: const [Icon(Icons.circle, size: 8, color: Color(0xFF00A36C)), SizedBox(width: 6), Text('Active', style: TextStyle(color: Color(0xFF00A36C), fontWeight: FontWeight.bold, fontSize: 12))])),
            ],
          ),
          const SizedBox(height: 24),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _buildUserInfoStat(gender, 'Gender', Icons.person_outline),
              _buildUserInfoStat(age, 'Age', Icons.calendar_today_outlined),
              _buildUserInfoStat(role[0].toUpperCase() + role.substring(1), 'Role', Icons.badge_outlined),
            ],
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              icon: const Icon(Icons.history_rounded, size: 18),
              label: const Text('View Scan History'),
              style: OutlinedButton.styleFrom(
                foregroundColor: primaryBlue,
                side: BorderSide(color: primaryBlue.withOpacity(0.2)),
                padding: const EdgeInsets.symmetric(vertical: 12),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              onPressed: () {
                showModalBottomSheet(
                  context: context,
                  isScrollControlled: true,
                  backgroundColor: Colors.transparent,
                  builder: (ctx) => _buildHistoryModal(context, ref, userId),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildUserInfoStat(String value, String label, IconData icon) {
    return Column(
      children: [
        Icon(icon, size: 20, color: textLight.withOpacity(0.5)),
        const SizedBox(height: 8),
        Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: primaryBlue)),
        Text(label, style: const TextStyle(fontSize: 12, color: textLight)),
      ],
    );
  }

  Widget _buildLargeDiagnosticCard({required String title, required String subtitle, required DiagnosticStatus status, required String timeAgo, required IconData icon, required VoidCallback onTap}) {
    final bool isAlert = status == DiagnosticStatus.alert;
    final Color bgColor = isAlert ? const Color(0xFFFFF7F7) : Colors.white;
    final Color iconBgColor = isAlert ? const Color(0xFFFFEAEA) : const Color(0xFFEAF8FC);
    final Color iconColor = isAlert ? const Color(0xFFE63946) : accentCyan;
    bool isHovered = false;

    return StatefulBuilder(
        builder: (context, setState) {
          return MouseRegion(
            onEnter: (_) => setState(() => isHovered = true),
            onExit: (_) => setState(() => isHovered = false),
            cursor: SystemMouseCursors.click,
            child: GestureDetector(
              onTap: onTap,
              child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  curve: Curves.easeOut,
                  transform: isHovered ? (Matrix4.identity()..translate(0.0, -4.0)) : Matrix4.identity(),
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                      color: bgColor,
                      borderRadius: BorderRadius.circular(24),
                      boxShadow: [
                        BoxShadow(color: primaryBlue.withOpacity(isHovered ? 0.12 : 0.05), blurRadius: isHovered ? 25 : 20, offset: isHovered ? const Offset(0, 8) : const Offset(0, 5))
                      ]
                  ),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: iconBgColor, borderRadius: BorderRadius.circular(16)), child: Icon(icon, color: iconColor, size: 28)),
                              if (isAlert) _buildBadge('RED ALERT', const Color(0xFFE63946), const Color(0xFFFFEAEA), showDot: true)
                            ]
                        ),
                        const SizedBox(height: 16),
                        Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: primaryBlue)),
                        Text(subtitle, style: const TextStyle(fontSize: 13, color: textLight)),
                        const SizedBox(height: 20),
                        SizedBox(height: 30, child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: List.generate(5, (index) => Padding(padding: const EdgeInsets.only(right: 12.0), child: CircleAvatar(radius: 4, backgroundColor: isAlert ? const Color(0xFFE63946).withOpacity(0.5 + (index * 0.1)) : textLight))))),
                        const Divider(height: 30),
                        Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(isAlert ? 'High Risk' : 'Analysis Complete', style: TextStyle(fontWeight: FontWeight.bold, color: isAlert ? const Color(0xFFE63946) : textDark)),
                              Row(children: [const Icon(Icons.access_time, size: 14, color: textLight), const SizedBox(width: 4), Text(timeAgo, style: const TextStyle(fontSize: 12, color: textLight))])
                            ]
                        ),
                        if (isAlert) ...[
                          const SizedBox(height: 16),
                          Container(
                              width: double.infinity,
                              padding: const EdgeInsets.symmetric(vertical: 12),
                              decoration: BoxDecoration(color: const Color(0xFFFFEAEA), borderRadius: BorderRadius.circular(12)),
                              child: Row(mainAxisAlignment: MainAxisAlignment.center, children: const [Icon(Icons.warning_amber_rounded, color: Color(0xFFE63946), size: 16), SizedBox(width: 8), Text('Abnormality detected — tap to review', style: TextStyle(color: Color(0xFFE63946), fontSize: 13, fontWeight: FontWeight.w500))])
                          )
                        ]
                      ]
                  )
              ),
            ),
          );
        }
    );
  }

  Widget _buildSmallDiagnosticCard({required String title, required String subtitle, required DiagnosticStatus status, required String timeAgo, required IconData icon, required VoidCallback onTap}) {
    Color badgeColor; Color badgeBg; String badgeText;
    switch (status) {
      case DiagnosticStatus.normal: badgeColor = const Color(0xFF00A36C); badgeBg = const Color(0xFFE6F7F0); badgeText = 'Ready'; break;
      case DiagnosticStatus.pending: badgeColor = const Color(0xFFF2994A); badgeBg = const Color(0xFFFFF5E6); badgeText = 'Pending'; break;
      default: badgeColor = textLight; badgeBg = bgLight; badgeText = 'Unknown';
    }
    bool isHovered = false;

    return StatefulBuilder(
        builder: (context, setState) {
          return MouseRegion(
            onEnter: (_) => setState(() => isHovered = true),
            onExit: (_) => setState(() => isHovered = false),
            cursor: SystemMouseCursors.click,
            child: GestureDetector(
              onTap: onTap,
              child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  curve: Curves.easeOut,
                  transform: isHovered ? (Matrix4.identity()..translate(0.0, -4.0)) : Matrix4.identity(),
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(24),
                      boxShadow: [
                        BoxShadow(color: primaryBlue.withOpacity(isHovered ? 0.12 : 0.05), blurRadius: isHovered ? 25 : 20, offset: isHovered ? const Offset(0, 8) : const Offset(0, 5))
                      ]
                  ),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Container(padding: const EdgeInsets.all(10), decoration: BoxDecoration(color: const Color(0xFFEAF8FC), borderRadius: BorderRadius.circular(12)), child: Icon(icon, color: accentCyan, size: 22)),
                              _buildBadge(badgeText, badgeColor, badgeBg, showDot: true)
                            ]
                        ),
                        const SizedBox(height: 16),
                        Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: primaryBlue)),
                        const SizedBox(height: 4),
                        Text(subtitle, style: const TextStyle(fontSize: 12, color: textLight), maxLines: 1, overflow: TextOverflow.ellipsis),
                        const SizedBox(height: 16),
                        Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(status == DiagnosticStatus.normal ? 'Normal' : 'Monitor', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13, color: status == DiagnosticStatus.normal ? const Color(0xFF00A36C) : const Color(0xFFF2994A))),
                              Row(children: [const Icon(Icons.access_time, size: 12, color: textLight), const SizedBox(width: 4), Text(timeAgo, style: const TextStyle(fontSize: 11, color: textLight))])
                            ]
                        )
                      ]
                  )
              ),
            ),
          );
        }
    );
  }

  Widget _buildBadge(String text, Color textColor, Color bgColor, {bool showDot = false}) {
    return Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: bgColor, borderRadius: BorderRadius.circular(20), border: Border.all(color: textColor.withOpacity(0.2))),
        child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (showDot) ...[Icon(Icons.circle, size: 6, color: textColor), const SizedBox(width: 4)],
              Text(text, style: TextStyle(color: textColor, fontSize: 10, fontWeight: FontWeight.bold))
            ]
        )
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
            selectedLabelStyle: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
            unselectedLabelStyle: const TextStyle(fontSize: 12),
            currentIndex: 0,
            onTap: (index) {
              if (index == 0) return;
              if (index == 1) context.goNamed('diagnostic');
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
              BottomNavigationBarItem(icon: Icon(Icons.analytics_outlined), label: 'Diagnostic'),
              BottomNavigationBarItem(icon: Icon(Icons.priority_high), label: 'Triage'),
              BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'AI Chat'),
            ]
                : const [
              BottomNavigationBarItem(icon: Icon(Icons.dashboard_rounded), label: 'Dashboard'),
              BottomNavigationBarItem(icon: Icon(Icons.analytics_outlined), label: 'Diagnostic'),
              BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'AI Chat'),
            ]
        )
    );
  }
}