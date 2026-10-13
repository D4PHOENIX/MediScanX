import 'package:flutter/foundation.dart';
import 'package:tflite_flutter/tflite_flutter.dart';
import 'package:image/image.dart' as img;

class SkinTfliteEngine {
  SkinTfliteEngine._privateConstructor();
  static final SkinTfliteEngine instance = SkinTfliteEngine._privateConstructor();
  factory SkinTfliteEngine() => instance;
  // -------------------------

  Interpreter? _interpreter;
  final int inputSize = 224;
  final int numClasses = 8; // 8 classes for the fp32 model

  // Human-readable labels mapped from the Python dictionary
  // IMPORTANT: Ensure this order matches the exact index order the ML model outputs!
  final List<String> _labels = [
    'Actinic keratoses',             // Index 0 (akiec)
    'Basal cell carcinoma',          // Index 1 (bcc)
    'Benign keratosis-like lesions', // Index 2 (bkl)
    'Dermatofibroma',                // Index 3 (df)
    'Melanoma',                      // Index 4 (mel)
    'Normal skin',                   // Index 5 (normal) - NEW!
    'Melanocytic nevi',              // Index 6 (nv) - SHIFTED
    'Vascular lesions'               // Index 7 (vasc) - SHIFTED
  ];

  // Standard ImageNet normalization values
  final List<double> mean = [0.485, 0.456, 0.406];
  final List<double> std = [0.229, 0.224, 0.225];

  // ==========================================
  // 1. INITIALIZE THE FP32 SKIN MODEL
  // ==========================================
  Future<void> loadModel() async {
    try {
      debugPrint('⏳ Loading FP32 Skin TFLite model...');
      _interpreter = await Interpreter.fromAsset('assets/models/skin_model/skin_multidomain_fp32.tflite');
      debugPrint('🟢 Skin Model loaded successfully!');

      if (_interpreter != null) {
        final inputTensor = _interpreter!.getInputTensor(0);
        debugPrint('📐 Skin Input Shape: ${inputTensor.shape}');
      }
    } catch (e) {
      debugPrint('🔴 Failed to load Skin model: $e');
    }
  }

  // ==========================================
  // 2. PREPROCESS & RUN INFERENCE
  // ==========================================
  /// Returns a Map of { "Disease Name": Probability Percentage }
  Future<Map<String, double>?> inferSkinImage(Uint8List imageBytes) async {
    if (_interpreter == null) {
      debugPrint('🔴 Inference failed: Skin Interpreter not initialized.');
      return null;
    }

    try {
      // 1. Decode and Resize
      img.Image? originalImage = img.decodeImage(imageBytes);
      if (originalImage == null) return null;
      img.Image resizedImage = img.copyResize(originalImage, width: inputSize, height: inputSize);

      // ==========================================
      // Channels-Last FP32 Tensor: [1, 224, 224, 3]
      // ==========================================
      var inputBuffer = List.generate(1, (batch) =>
          List.generate(inputSize, (y) =>
              List.generate(inputSize, (x) =>
                  List.filled(3, 0.0) // Float32
              )
          )
      );

      // 3. Extract and Normalize Pixels
      for (int y = 0; y < inputSize; y++) {
        for (int x = 0; x < inputSize; x++) {
          final pixel = resizedImage.getPixel(x, y);

          // Convert RGB to float (0.0 to 1.0)
          double r = pixel.r / 255.0;
          double g = pixel.g / 255.0;
          double b = pixel.b / 255.0;

          // Apply ImageNet Normalization
          double rNorm = (r - mean[0]) / std[0];
          double gNorm = (g - mean[1]) / std[1];
          double bNorm = (b - mean[2]) / std[2];

          // Assign directly to float buffer
          inputBuffer[0][y][x][0] = rNorm;
          inputBuffer[0][y][x][1] = gNorm;
          inputBuffer[0][y][x][2] = bNorm;
        }
      }

      // 4. Prepare FP32 output tensor for 8 classes
      var outputBuffer = List.filled(1 * numClasses, 0.0).reshape([1, numClasses]);

      // 5. Run Inference
      _interpreter!.run(inputBuffer, outputBuffer);

      // 6. Map to labels
      Map<String, double> mappedResults = {};

      for (int i = 0; i < numClasses; i++) {
        // Output is already a float probability (often from a softmax layer)
        double floatProbability = outputBuffer[0][i];

        // Map to string label
        String diseaseName = i < _labels.length ? _labels[i] : 'Unknown Class $i';
        mappedResults[diseaseName] = floatProbability;
      }

      return mappedResults;

    } catch (e) {
      debugPrint('🔴 Error during Skin inference: $e');
      return null;
    }
  }

  // ==========================================
  // 3. CLEANUP
  // ==========================================
  void dispose() {
    _interpreter?.close();
  }
}