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
  final int numClasses = 7; // Matching the length of the provided dictionary

  // Human-readable labels mapped from the Python dictionary
  // IMPORTANT: Ensure this order matches the exact index order the ML model outputs!
  final List<String> _labels = [
    'Actinic Keratoses',    // 0: akiec
    'Basal Cell Carcinoma', // 1: bcc
    'Benign Keratosis',     // 2: bkl
    'Dermatofibroma',       // 3: df
    'Melanoma',             // 4: mel
    'Melanocytic Nevi',     // 5: nv
    'Vascular Lesions'      // 6: vasc
  ];

  // Standard ImageNet normalization values
  final List<double> mean = [0.485, 0.456, 0.406];
  final List<double> std = [0.229, 0.224, 0.225];

  // Quantization parameters
  double _inputScale = 1.0;
  int _inputZeroPoint = 0;
  double _outputScale = 1.0;
  int _outputZeroPoint = 0;

  // ==========================================
  // 1. INITIALIZE THE INT8 SKIN MODEL
  // ==========================================
  Future<void> loadModel() async {
    try {
      debugPrint('⏳ Loading INT8 Skin TFLite model...');
      _interpreter = await Interpreter.fromAsset('assets/models/skin_model/skin_model.tflite');
      debugPrint('🟢 Skin Model loaded successfully!');

      if (_interpreter != null) {
        final inputTensor = _interpreter!.getInputTensor(0);
        final outputTensor = _interpreter!.getOutputTensor(0);

        debugPrint('📐 Skin Input Shape: ${inputTensor.shape}');

        // Auto-extract the quantization math from the TFLite file
        final inputParams = inputTensor.params;
        _inputScale = inputParams.scale == 0 ? 1.0 : inputParams.scale;
        _inputZeroPoint = inputParams.zeroPoint;

        final outputParams = outputTensor.params;
        _outputScale = outputParams.scale == 0 ? 1.0 : outputParams.scale;
        _outputZeroPoint = outputParams.zeroPoint;
      }
    } catch (e) {
      debugPrint('🔴 Failed to load Skin model: $e');
    }
  }

  // ==========================================
  // 2. PREPROCESS, QUANTIZE & RUN INFERENCE
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
      // FIXED: Channels-Last INT8 Tensor: [1, 224, 224, 3]
      // ==========================================
      var inputBuffer = List.generate(1, (batch) =>
          List.generate(inputSize, (y) =>
              List.generate(inputSize, (x) =>
                  List.filled(3, 0) // The 3 color channels are now at the END
              )
          )
      );

      // 3. Extract, Normalize, and Quantize Pixels
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

          // Quantize to INT8: (value / scale) + zero_point, then clamp
          // FIXED: The array access order is now [0][y][x][channel]
          inputBuffer[0][y][x][0] = ((rNorm / _inputScale) + _inputZeroPoint).round().clamp(-128, 127);
          inputBuffer[0][y][x][1] = ((gNorm / _inputScale) + _inputZeroPoint).round().clamp(-128, 127);
          inputBuffer[0][y][x][2] = ((bNorm / _inputScale) + _inputZeroPoint).round().clamp(-128, 127);
        }
      }

      // 4. Prepare INT8 output tensor for 7 classes
      var outputBuffer = List.filled(1 * numClasses, 0).reshape([1, numClasses]);

      // 5. Run Inference
      _interpreter!.run(inputBuffer, outputBuffer);

      // 6. De-Quantize the output and map to labels
      Map<String, double> mappedResults = {};

      for (int i = 0; i < numClasses; i++) {
        int rawInt8Output = outputBuffer[0][i];

        // De-quantize back to float probability
        double floatProbability = (rawInt8Output - _outputZeroPoint) * _outputScale;

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