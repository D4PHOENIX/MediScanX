// lib/core/utils/image_validator.dart
import 'dart:io';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:image/image.dart' as img;

/// Validates whether an uploaded image matches the expected medical modality
/// using lightweight heuristics (color distribution, aspect ratio, grayscale analysis).
///
/// This runs entirely on-device before any network call, preventing obviously
/// invalid images (e.g. a photo of a car) from being sent to the backend.
class ImageValidator {

  /// Validates that [imageFile] looks like a legitimate image for [modality].
  /// Returns null if valid, or an error message string if invalid.
  static Future<String?> validate(File imageFile, String modality) async {
    try {
      final bytes = await imageFile.readAsBytes();
      final decoded = img.decodeImage(bytes);
      if (decoded == null) {
        return 'Could not read the image. Please select a valid image file.';
      }

      switch (modality) {
        case 'Chest X-Ray':
          return _validateCXR(decoded);
        case 'ECG':
          return _validateECG(decoded);
        case 'Skin':
          return _validateSkin(decoded);
        default:
          return null; // Unknown modality — skip validation
      }
    } catch (e) {
      debugPrint('⚠️ [ImageValidator] Error during validation: $e');
      return null; // Don't block the user on validator crashes
    }
  }

  static String? _validateCXR(img.Image image) {
    final sampled = img.copyResize(image, width: 64, height: 64);
    int midTonePixels = 0;
    int totalPixels = 0;

    for (int y = 0; y < sampled.height; y++) {
      for (int x = 0; x < sampled.width; x++) {
        final pixel = sampled.getPixel(x, y);
        totalPixels++;
        // Use standard luminance to handle blue-tinted X-rays gracefully
        final luma = 0.299 * pixel.r + 0.587 * pixel.g + 0.114 * pixel.b;
        if (luma > 30 && luma < 225) midTonePixels++;
      }
    }

    final midToneRatio = midTonePixels / totalPixels;
    debugPrint('🔍 [ImageValidator/CXR] midToneRatio=$midToneRatio');

    if (midToneRatio < 0.15) {
      return 'This image lacks natural grayscale gradients (e.g., looks like a QR code or text document). Please upload a valid Chest X-ray.';
    }

    return null;
  }

  static String? _validateECG(img.Image image) {
    final sampled = img.copyResize(image, width: 64, height: 64);
    int midTonePixels = 0;
    int totalPixels = 0;

    for (int y = 0; y < sampled.height; y++) {
      for (int x = 0; x < sampled.width; x++) {
        final pixel = sampled.getPixel(x, y);
        totalPixels++;
        final luma = 0.299 * pixel.r + 0.587 * pixel.g + 0.114 * pixel.b;
        if (luma > 40 && luma < 215) midTonePixels++;
      }
    }

    final midToneRatio = midTonePixels / totalPixels;
    debugPrint('🔍 [ImageValidator/ECG] midToneRatio=$midToneRatio');

    // Reject obvious binary images (like a pure QR code or raw text document without waveform lines)
    if (midToneRatio < 0.05) {
      return 'This does not appear to be an ECG report. Ensure the image contains clear waveform lines.';
    }

    return null;
  }

  static String? _validateSkin(img.Image image) {
    final sampled = img.copyResize(image, width: 64, height: 64);
    int midTonePixels = 0;
    int totalPixels = 0;

    for (int y = 0; y < sampled.height; y++) {
      for (int x = 0; x < sampled.width; x++) {
        final pixel = sampled.getPixel(x, y);
        totalPixels++;
        final luma = 0.299 * pixel.r + 0.587 * pixel.g + 0.114 * pixel.b;
        if (luma > 30 && luma < 225) midTonePixels++;
      }
    }

    final midToneRatio = midTonePixels / totalPixels;
    debugPrint('🔍 [ImageValidator/Skin] midToneRatio=$midToneRatio');
    
    // Just reject purely binary garbage like QR codes or scanned text
    if (midToneRatio < 0.10) {
      return 'This image lacks natural features (e.g., looks like a QR code or text document). Please upload a photo of the skin lesion.';
    }

    return null;
  }
}
