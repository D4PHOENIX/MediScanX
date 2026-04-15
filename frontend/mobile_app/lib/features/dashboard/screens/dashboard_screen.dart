// lib/features/dashboard/screens/dashboard_screen.dart
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:drift/drift.dart' as drift;
import '../../auth/providers/auth_state_provider.dart';
import '../../auth/providers/database_provider.dart';

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
                            _buildUserCard(userName, displayUsername, gender, age, userType),
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
                              onTap: () => innerContext.goNamed('diagnostic'),
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
                                    onTap: () => innerContext.goNamed('diagnostic'),
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
                                    onTap: () => innerContext.goNamed('diagnostic'),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 24),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              bottomNavigationBar: _buildBottomNav(context),
            );
          },
        );
      },
    );
  }

  // ==========================================
  // YOUR ORIGINAL RESTORED UI COMPONENTS
  // ==========================================

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

  Widget _buildUserCard(String name, String id, String gender, String age, String role) {
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

  Widget _buildBottomNav(BuildContext context) {
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
              if (index == 2) context.goNamed('ai_chat');
              if (index == 3) context.goNamed('referral');
            },
            items: const [
              BottomNavigationBarItem(icon: Icon(Icons.dashboard_rounded), label: 'Dashboard'),
              BottomNavigationBarItem(icon: Icon(Icons.analytics_outlined), label: 'Diagnostic'),
              BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'AI Chat'),
              BottomNavigationBarItem(icon: Icon(Icons.qr_code_scanner), label: 'Referral')
            ]
        )
    );
  }
}