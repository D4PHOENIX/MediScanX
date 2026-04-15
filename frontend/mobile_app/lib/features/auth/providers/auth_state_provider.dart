// lib/features/auth/providers/auth_state_provider.dart

import 'package:riverpod/riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart' as supabase;
import '../models/auth_models.dart';

class AuthStateNotifier extends StateNotifier<AsyncValue<AuthResponse?>> {
  AuthStateNotifier() : super(const AsyncValue.data(null));

  // Get the global Supabase client instance
  final _supabaseClient = supabase.Supabase.instance.client;

  String _normalizeRole(String? rawRole) {
    return rawRole?.toLowerCase() == 'doctor' ? 'Doctor' : 'Patient';
  }

  // ==========================================
  // 1. LIVE LOGIN LOGIC
  // ==========================================
  Future<bool> login(String usernameOrEmail, String password) async {
    state = const AsyncValue.loading();

    try {
      final response = await _supabaseClient.auth.signInWithPassword(
        email: usernameOrEmail,
        password: password,
      );

      final user = response.user;

      if (user != null) {
        final metadata = user.userMetadata;
        final normalizedRole = _normalizeRole(
          (metadata?['role'] ?? metadata?['userType'])?.toString(),
        );

        final authResponse = AuthResponse(
          success: true,
          message: 'Login successful',
          userId: user.id,
          userType: normalizedRole,
          fullName: (metadata?['full_name'] ?? metadata?['fullName'] ?? user.email)?.toString(),
          gender: null,
          age: null,
        );

        state = AsyncValue.data(authResponse);
        return true;
      } else {
        state = AsyncValue.error('Unknown login error occurred.', StackTrace.current);
        return false;
      }

    } on supabase.AuthException catch (e) {
      state = AsyncValue.error(e.message, StackTrace.current);
      return false;
    } catch (e) {
      state = AsyncValue.error('Network error. Please try again.', StackTrace.current);
      return false;
    }
  }

  // ==========================================
  // 2. LIVE LOGOUT LOGIC
  // ==========================================
  Future<void> logout() async {
    state = const AsyncValue.loading();
    await _supabaseClient.auth.signOut();
    state = const AsyncValue.data(null);
  }

  // ==========================================
  // 3. LIVE SIGNUP LOGIC
  // ==========================================
  Future<bool> signup(SignupRequest request) async {
    state = const AsyncValue.loading();

    try {
      final normalizedRole = _normalizeRole(request.userType);

      final response = await _supabaseClient.auth.signUp(
          email: request.email,
          password: request.password,
          data: {
            'full_name': request.fullName,
            'username': request.username,
            'role': normalizedRole,
            'gender': request.gender,
            'date_of_birth': request.dateOfBirth,
            'phone_number': request.phoneNumber,
            'location': request.location,
            'specialization': request.specialization,
            'current_hospital': request.currentHospital,
          }
      );

      if (response.user != null) {
        state = const AsyncValue.data(null);
        return true;
      } else {
        state = AsyncValue.error('Signup failed. Please try again.', StackTrace.current);
        return false;
      }
    } on supabase.AuthException catch (e) {
      state = AsyncValue.error(e.message, StackTrace.current);
      return false;
    } catch (e) {
      state = AsyncValue.error('Network error during signup.', StackTrace.current);
      return false;
    }
  }

  // ==========================================
  // 4. LIVE PASSWORD RESET LOGIC
  // ==========================================

  // Send the OTP Code to the user's email
  Future<bool> resetPassword(String email) async {
    state = const AsyncValue.loading();
    try {
      await _supabaseClient.auth.resetPasswordForEmail(email);
      state = const AsyncValue.data(null);
      return true;
    } on supabase.AuthException catch (e) {
      state = AsyncValue.error(e.message, StackTrace.current);
      return false;
    } catch (e) {
      state = AsyncValue.error('Failed to send reset email.', StackTrace.current);
      return false;
    }
  }

  // Verify the 6-digit code they typed in
  Future<bool> verifyResetCode(String email, String code) async {
    state = const AsyncValue.loading();
    try {
      await _supabaseClient.auth.verifyOTP(
        type: supabase.OtpType.recovery,
        email: email,
        token: code,
      );
      state = const AsyncValue.data(null);
      return true;
    } on supabase.AuthException catch (e) {
      state = AsyncValue.error('Invalid or expired code.', StackTrace.current);
      return false;
    } catch (e) {
      state = AsyncValue.error('Verification failed.', StackTrace.current);
      return false;
    }
  }

  // Save the new password
  Future<bool> confirmNewPassword(String email, String code, String newPw, String confirm) async {
    if (newPw != confirm) {
      state = AsyncValue.error('Passwords do not match.', StackTrace.current);
      return false;
    }

    state = const AsyncValue.loading();
    try {
      await _supabaseClient.auth.updateUser(
        supabase.UserAttributes(password: newPw),
      );
      state = const AsyncValue.data(null);
      return true;
    } on supabase.AuthException catch (e) {
      state = AsyncValue.error(e.message, StackTrace.current);
      return false;
    } catch (e) {
      state = AsyncValue.error('Failed to update password.', StackTrace.current);
      return false;
    }
  }

  // ==========================================
  // 5. UTILITY
  // ==========================================
  void clearMessages() => state.hasError ? state = const AsyncValue.data(null) : null;
}

// Update the Provider Definition
final authStateProvider = StateNotifierProvider<AuthStateNotifier, AsyncValue<AuthResponse?>>((ref) {
  return AuthStateNotifier();
});