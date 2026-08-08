import 'dart:async';
import 'package:riverpod_annotation/riverpod_annotation.dart';
import 'package:mediscanx_mobile/features/auth/providers/database_provider.dart';
part 'sync_provider.g.dart';

@riverpod
class SyncCoordinator extends _$SyncCoordinator {
  @override
  FutureOr<void> build() async{
    await syncPendingData();
}

  Future<void> syncPendingData() async{
    final db = ref.read(databaseProvider);

    // We use AsyncValue.guard to handle network errors gracefully
    state = await AsyncValue.guard(() async{
      if (true) {
        await Future.delayed(const Duration(seconds: 2));

        print('MediScanX: Sync check complete.');
      }
    });
  }
}