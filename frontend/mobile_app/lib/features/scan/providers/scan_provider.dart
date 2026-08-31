
import 'package:riverpod_annotation/riverpod_annotation.dart';
import '../models/scan_model.dart';

part 'scan_provider.g.dart';

@riverpod
class ScanState extends _$ScanState {
  @override
  FutureOr<ScanResult?> build() {
    // Initial state is null because no scan has been performed yet
    return null;
  }

  /// Entry point for running TFLite inference
  Future<void> runInference(String imagePath) async {
    // Set state to loading so the UI can show a spinner
    state = const AsyncLoading();

    state = await AsyncValue.guard(() async {
      // 1. TODO: TFLite Model Loading (Task 2)
      // 2. TODO: Pre-processing imagePath

      // Simulating a heavy AI processing delay (3 seconds)
      await Future.delayed(const Duration(seconds: 3));

      // Mock Result: Replace this with actual TFLite output later
      return ScanResult(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        label: 'Normal ECG Pattern',
        confidence: 0.985,
        timestamp: DateTime.now(),
        remarks: 'No abnormalities detected in the current scan.',
        isSynced: false,
      );
    });
  }

  /// Clears the current scan result to allow a new scan
  void reset() {
    state = const AsyncData(null);
  }
}