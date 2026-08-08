import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers/sync_debug_provider.dart';

class SyncDebugScreen extends ConsumerWidget {
  const SyncDebugScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final syncStatusAsync = ref.watch(syncStatusProvider);
    final profileDebugAsync = ref.watch(profileSyncDebugProvider);

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.goNamed('dashboard'),
          tooltip: 'Back to Dashboard',
        ),
        title: const Text('Sync Debug'),
        actions: [
          IconButton(
            onPressed: () {
              ref.invalidate(syncStatusProvider);
              ref.invalidate(profileSyncDebugProvider);
            },
            icon: const Icon(Icons.refresh),
            tooltip: 'Refresh now',
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: syncStatusAsync.when(
                loading: () => const Text('Loading PowerSync status...'),
                error: (error, stack) => Text('PowerSync status error: $error'),
                data: (status) => Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'PowerSync Status',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 8),
                    Text('connected: ${status.connected}'),
                    Text('hasSynced: ${status.hasSynced}'),
                    Text('lastSyncedAt: ${status.lastSyncedAt ?? '--'}'),
                    Text('raw: $status'),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: profileDebugAsync.when(
                loading: () => const Text('Loading profile snapshot...'),
                error: (error, stack) => Text('Profile snapshot error: $error'),
                data: (snapshot) => Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Profile Snapshot',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 8),
                    Text('capturedAt: ${snapshot.capturedAt}'),
                    Text('userId: ${snapshot.userId ?? '--'}'),
                    Text('email: ${snapshot.email ?? '--'}'),
                    Text('normalizedRole: ${snapshot.normalizedRole}'),
                    Text('expectedTable: ${snapshot.expectedTable}'),
                    Text('foundInExpectedTable: ${snapshot.foundInExpectedTable}'),
                    Text('foundInOtherTable: ${snapshot.foundInOtherTable}'),
                    Text('fullName: ${snapshot.fullName ?? '--'}'),
                    Text('username: ${snapshot.username ?? '--'}'),
                    Text('syncStatus: ${snapshot.syncStatus ?? '--'}'),
                    const SizedBox(height: 8),
                    Text('diagnosis: ${snapshot.diagnosis}'),
                    const SizedBox(height: 8),
                    const Text(
                      'auth metadata',
                      style: TextStyle(fontWeight: FontWeight.w600),
                    ),
                    Text(snapshot.metadata.toString()),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

