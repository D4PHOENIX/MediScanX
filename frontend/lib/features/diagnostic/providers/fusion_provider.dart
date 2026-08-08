import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/fusion_models.dart';
import '../services/fusion_service.dart';

final fusionServiceProvider = Provider<FusionService>((ref) {
  return FusionService();
});

class FusionNotifier extends AsyncNotifier<FusionResponse?> {
  @override
  Future<FusionResponse?> build() async {
    return null; // Initial state is no response
  }

  Future<void> triggerFusion({
    List<String>? selectedScanIds,
  }) async {
    state = const AsyncValue.loading();
    try {
      final request = FusionRequest(
        selectedScanIds: selectedScanIds,
      );

      final service = ref.read(fusionServiceProvider);
      final response = await service.fuseDiagnostics(request);

      state = AsyncValue.data(response);
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }
}

final fusionProvider =
    AsyncNotifierProvider<FusionNotifier, FusionResponse?>(() {
  return FusionNotifier();
});