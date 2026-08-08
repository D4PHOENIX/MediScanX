import 'dart:typed_data';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mediscanx_mobile/core/ml/skin_tflite_engine.dart';

// ==========================================
// 1. THE STATE OBJECT
// ==========================================
class SkinDiagnosticState {
  final bool isLoading;
  final Uint8List? imageBytes;
  final Map<String, double>? results;
  final String? errorMessage;

  SkinDiagnosticState({
    this.isLoading = false,
    this.imageBytes,
    this.results,
    this.errorMessage,
  });

  // copyWith allows us to update one piece of state (like turning on a loading spinner)
  // without losing the other data (like the image we just took).
  SkinDiagnosticState copyWith({
    bool? isLoading,
    Uint8List? imageBytes,
    Map<String, double>? results,
    String? errorMessage,
    bool clearError = false,
  }) {
    return SkinDiagnosticState(
      isLoading: isLoading ?? this.isLoading,
      imageBytes: imageBytes ?? this.imageBytes,
      results: results ?? this.results,
      errorMessage: clearError ? null : (errorMessage ?? this.errorMessage),
    );
  }
}

// ==========================================
// 2. THE NOTIFIER (THE BRAIN)
// ==========================================
class SkinDiagnosticNotifier extends Notifier<SkinDiagnosticState> {
  final ImagePicker _picker = ImagePicker();

  @override
  SkinDiagnosticState build() {
    return SkinDiagnosticState(); // Start with a completely blank state
  }

  /// Opens the camera or gallery, captures the image, and feeds it to the ML engine.
  Future<void> analyzeImage(ImageSource source) async {
    // 1. Clear any old errors
    state = state.copyWith(clearError: true);

    try {
      // 2. Open Camera/Gallery
      // We limit resolution here to save RAM before the ML engine resizes it to 224x224
      final XFile? photo = await _picker.pickImage(
        source: source,
        maxWidth: 800,
        maxHeight: 800,
      );

      // If the user hits the "Back" button and cancels the camera
      if (photo == null) return;

      // 3. Read the image and trigger the Loading Spinner in the UI
      final bytes = await photo.readAsBytes();
      state = state.copyWith(isLoading: true, imageBytes: bytes);

      // 4. Send to the ML Engine (using our Singleton)
      final results = await SkinTfliteEngine().inferSkinImage(bytes);

      if (results == null) {
        state = state.copyWith(
          isLoading: false,
          errorMessage: "Failed to process the image. Please try again.",
        );
        return;
      }

      // 5. Update UI with the final medical results!
      state = state.copyWith(
        isLoading: false,
        results: results,
      );

    } catch (e) {
      // Catch any random crashes gracefully so the app doesn't freeze
      state = state.copyWith(
        isLoading: false,
        errorMessage: "An error occurred during analysis: $e",
      );
    }
  }

  /// Clears the state so the user can scan a new patient
  void reset() {
    state = SkinDiagnosticState();
  }
}

// ==========================================
// 3. THE RIVERPOD EXPORT
// ==========================================
final skinDiagnosticProvider = NotifierProvider<SkinDiagnosticNotifier, SkinDiagnosticState>(() {
  return SkinDiagnosticNotifier();
});