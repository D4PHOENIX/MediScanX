import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:powersync/powersync.dart';

import 'package:mediscanx_mobile/features/debug/providers/sync_debug_provider.dart';
import 'package:mediscanx_mobile/features/debug/screens/sync_debug_screen.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Sync debug screen renders provider data',
      (WidgetTester tester) async {
    final fakeSnapshot = ProfileSyncDebugSnapshot(
      capturedAt: DateTime(2026, 4, 15, 12, 0),
      userId: 'user-123',
      email: 'debug@test.com',
      metadata: const {'role': 'Doctor', 'username': 'doc123'},
      normalizedRole: 'Doctor',
      expectedTable: 'doctor_profiles',
      foundInExpectedTable: true,
      foundInOtherTable: false,
      fullName: 'Debug Doctor',
      username: 'doc123',
      syncStatus: 'synced',
      diagnosis: 'Profile row found in expected table.',
    );

    final fakeStatus = SyncStatus(
      connected: true,
      connecting: false,
      downloading: false,
      uploading: false,
      hasSynced: true,
      lastSyncedAt: DateTime(2026, 4, 15, 11, 59),
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          syncStatusProvider.overrideWith((ref) => Stream.value(fakeStatus)),
          profileSyncDebugProvider
              .overrideWith((ref) => Stream.value(fakeSnapshot)),
        ],
        child: const MaterialApp(
          home: SyncDebugScreen(),
        ),
      ),
    );

    await tester.pump();

    expect(find.text('Sync Debug'), findsOneWidget);
    expect(find.text('connected: true'), findsOneWidget);
    expect(find.text('hasSynced: true'), findsOneWidget);
    expect(find.textContaining('userId: user-123'), findsOneWidget);
    expect(find.textContaining('expectedTable: doctor_profiles'), findsOneWidget);
    expect(find.textContaining('diagnosis: Profile row found in expected table.'),
        findsOneWidget);
  });
}
