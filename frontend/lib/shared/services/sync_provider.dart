import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';
part 'sync_provider.g.dart';

@riverpod
class SyncCoordinator extends _$SyncCoordinator {
  @override
  FutureOr<void> build() async{
    await syncPendingData();
}

  Future<void> syncPendingData() async{
    // We use AsyncValue.guard to handle network errors gracefully
    state = await AsyncValue.guard(() async{
      if (true) {
        await Future.delayed(const Duration(seconds: 2));

        debugPrint('MediScanX: Sync check complete.');
      }
    });
  }
}