import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import '../../../core/network/api_client.dart';
import '../models/fusion_models.dart';

class NetworkException implements Exception {
  final String message;
  NetworkException(this.message);
  @override
  String toString() => message;
}

class FusionService {
  final ApiClient _apiClient = ApiClient();

  Future<FusionResponse?> fuseDiagnostics(FusionRequest request) async {
    try {
      debugPrint('🧠 Sending data to Master Doctor (Fusion API)...');

      // EXACT ENDPOINT FROM THE PDF GUIDE
      Response response = await _apiClient.dio.post(
        '/fusion/fuse',
        data: request.toJson(),
      );

      if (response.statusCode == 200) {
        debugPrint('✅ Multimodal Fusion Complete!');
        return FusionResponse.fromJson(response.data);
      }
      return null;
    } on DioException catch (e) {
      debugPrint('🔴 Fusion API DioException: ${e.message}');
      if (e.type == DioExceptionType.connectionError ||
          e.type == DioExceptionType.connectionTimeout ||
          e.error is SocketException) {
        // Online-only architecture: immediately throw network error for the UI
        throw NetworkException(
            'Master AI Fusion requires an active internet connection to synthesize clinical data.');
      }
      throw Exception('Failed to synthesize data: ${e.message}');
    } catch (e) {
      debugPrint('🔴 Fusion API Failed: $e');
      throw Exception('An unexpected error occurred during AI fusion.');
    }
  }
}