import 'dart:io';
import 'package:dio/dio.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

class ErrorHelper {
  /// Converts a technical Exception or Error into a human-readable string for the UI.
  static String getHumanReadableError(dynamic error) {
    if (error == null) return 'An unexpected error occurred.';

    final errorStr = error.toString().toLowerCase();

    // 1. Check for Network / Socket issues first
    if (error is SocketException || errorStr.contains('socketexception') || errorStr.contains('failed host lookup')) {
      return 'No internet connection. Please check your network and try again.';
    }

    // 2. Dio (API / Network) Errors
    if (error is DioException) {
      if (error.type == DioExceptionType.connectionTimeout || error.type == DioExceptionType.receiveTimeout) {
        return 'The connection timed out. Please check your internet and try again.';
      }
      if (error.type == DioExceptionType.connectionError) {
        return 'Could not connect to the server. Please verify your internet connection.';
      }
      if (error.response?.statusCode != null) {
        if (error.response!.statusCode! >= 500) {
          return 'Our servers are currently experiencing issues. Please try again later.';
        }
      }
      return 'A network error occurred. Please try again.';
    }

    // 3. Supabase Auth Errors
    if (error is AuthException) {
      final msg = error.message.toLowerCase();
      if (msg.contains('invalid login credentials')) {
        return 'Incorrect email or password. Please try again.';
      }
      if (msg.contains('already registered') || msg.contains('user already exists')) {
        return 'An account with this email already exists.';
      }
      if (msg.contains('email link')) {
        return 'The magic link has expired or is invalid. Please request a new one.';
      }
      if (msg.contains('rate limit')) {
        return 'Too many attempts. Please wait a moment before trying again.';
      }
      return error.message; // Fallback to Supabase's provided message
    }

    // 4. Supabase Database Errors
    if (error is PostgrestException) {
      if (error.code == '23505') {
        return 'This record already exists in the system.';
      }
      return 'A database error occurred. Please try again later.';
    }

    // 5. General connection refused
    if (errorStr.contains('connection refused')) {
      return 'The server is currently offline or unreachable. Please try again later.';
    }

    // 6. Generic Exception (allow custom messages to pass through)
    if (error is Exception) {
      final msg = error.toString();
      if (msg.startsWith('Exception: ')) {
        return msg.substring(11); // Remove the "Exception: " prefix
      }
      return msg;
    }

    // 7. Default Fallback
    return 'An unexpected error occurred. Please try again.';
  }
}
