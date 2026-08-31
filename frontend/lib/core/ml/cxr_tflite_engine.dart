import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:tflite_flutter/tflite_flutter.dart';
import 'package:image/image.dart' as img;

class TFLiteEngine {
  Interpreter? _interpreter;
  static const int inputSize = 320;

  // --- THE ML DEVELOPER'S EXACT NUMBERS ---
  static const double inputScale = 0.01865844801068306;
  static const int inputZeroPoint = -14;

  static const double outputScale = 0.0661005973815918;
  static const int outputZeroPoint = 10;
  // ----------------------------------------

  // ==========================================
  // 1. INITIALIZE THE MODEL
  // ==========================================
  Future<void> loadModel() async {
    try {
      _interpreter = await Interpreter.fromAsset('assets/models/cxr_model/cxr_model.tflite');
      debugPrint('🟢 Local TFLite Model loaded successfully');
    } catch (e) {
      debugPrint('🔴 Failed to load model: $e');
    }
  }

  // ==========================================
  // 2. RUN INFERENCE (THE PREDICTION)
  // ==========================================
  Future<List<double>?> predict(File imageFile) async {
    if (_interpreter == null) {
      debugPrint('⚠️ Model not loaded yet');
      return null;
    }

    try {
      final inputTensor = await _preprocessImage(imageFile);
      if (inputTensor == null) return null;

      var outputBuffer = List.generate(1, (_) => List.filled(20, 0));
      _interpreter!.run(inputTensor, outputBuffer);

      // Extract the raw int8 scores
      final rawScores = outputBuffer[0];

      // Use the ML Developer's exact output math to convert to percentages!
      List<double> probabilities = rawScores.map((rawValue) {
        double percent = (rawValue - outputZeroPoint) * outputScale;
        return percent.clamp(0.0, 1.0);
      }).toList();

      debugPrint('📊 Final Probabilities: $probabilities');
      return probabilities;

    } catch (e) {
      debugPrint('🔴 Prediction failed: $e');
      return null;
    }
  }

  // ==========================================
  // 3. INT8 IMAGE PREPROCESSING
  // ==========================================
  Future<List<List<List<List<int>>>>?> _preprocessImage(File imageFile) async {
    final rawBytes = await imageFile.readAsBytes();
    img.Image? decodedImage = img.decodeImage(rawBytes);
    if (decodedImage == null) return null;

    img.Image resizedImage = img.copyResize(decodedImage, width: inputSize, height: inputSize);

    List<List<List<List<int>>>> input = List.generate(
      1, (b) => List.generate(
      inputSize, (y) => List.generate(
      inputSize, (x) => List.generate(3, (c) => 0),
    ),
    ),
    );

    for (int y = 0; y < inputSize; y++) {
      for (int x = 0; x < inputSize; x++) {
        final pixel = resizedImage.getPixel(x, y);

        // 1. Normalize the pixel (0.0 to 1.0)
        double rNorm = pixel.r / 255.0;
        double gNorm = pixel.g / 255.0;
        double bNorm = pixel.b / 255.0;

        // 2. Use the ML Developer's exact input math to safely convert back to int8
        input[0][y][x][0] = ((rNorm / inputScale).round() + inputZeroPoint).clamp(-128, 127);
        input[0][y][x][1] = ((gNorm / inputScale).round() + inputZeroPoint).clamp(-128, 127);
        input[0][y][x][2] = ((bNorm / inputScale).round() + inputZeroPoint).clamp(-128, 127);
      }
    }

    return input;
  }

  void dispose() {
    _interpreter?.close();
  }
}