import 'package:flutter/foundation.dart';
import 'package:riverpod/riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart' as supabase;

// --- ADDED THESE THREE IMPORTS ---
import 'package:mediscanx_mobile/core/database/database_manager.dart';
import 'package:mediscanx_mobile/core/database/supabase_connector.dart';
import 'package:mediscanx_mobile/core/config/env_config.dart';
import 'package:mediscanx_mobile/core/utils/error_helper.dart'; // NEW IMPORT

import '../models/auth_models.dart';

class AuthStateNotifier extends StateNotifier<AsyncValue<AuthResponse?>> {
  AuthStateNotifier() : super(const AsyncValue.loading());

  // Get the global Supabase client instance
  final _supabaseClient = supabase.Supabase.instance.client;

  // ==========================================
  // 0. OFFLINE VALIDATION (APP LAUNCH)
  // ==========================================
  Future<void> initialize() async {
    state = const AsyncValue.loading();

    // 1. Check if Supabase has a cached session token on the device
    final session = _supabaseClient.auth.currentSession;

    if (session != null) {
      // 2. We are OFFLINE VALIDATED! Rebuild the AuthResponse from local data
      final user = session.user;
      final metadata = user.userMetadata;
      final normalizedRole = _normalizeRole(
        (metadata?['role'] ?? metadata?['userType'])?.toString(),
      );

      final authResponse = AuthResponse(
        success: true,
        message: 'Restored offline session',
        userId: user.id,
        userType: normalizedRole,
        fullName: (metadata?['full_name'] ?? metadata?['fullName'] ?? user.email)?.toString(),
        gender: null, // PowerSync/Drift handles loading these details on the Dashboard
        age: null,
      );

      // --- NEW: Verify the public profile actually exists! ---
      // If a developer deleted the user from public.patient_records but NOT auth.users,
      // or if the account is broken, log them out immediately on app start.
      try {
        final table = normalizedRole == 'Doctor' ? 'doctor_profiles' : 'patient_records';
        final profileCheck = await _supabaseClient
            .from(table)
            .select('user_id')
            .eq('user_id', user.id)
            .maybeSingle();
            
        if (profileCheck == null) {
          debugPrint('🔴 Profile missing for active session! Logging out...');
          await _supabaseClient.auth.signOut();
          state = AsyncValue.error('User does not exist. Please create a new account.', StackTrace.current);
          return;
        }
      } catch (e) {
        debugPrint('Warning: Could not verify profile existence during init: $e');
        // Let it proceed if offline, as the user might legitimately be offline.
      }

      state = AsyncValue.data(authResponse);
    } else {
      // 3. No token found, user must login manually
      state = const AsyncValue.data(null);
    }
  }

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

        // --- NEW: Verify the public profile actually exists! ---
        // If a developer deleted the user from public.patient_records but NOT auth.users,
        // we must reject the login to prevent Foreign Key crashes later.
        try {
          final table = normalizedRole == 'Doctor' ? 'doctor_profiles' : 'patient_records';
          final profileCheck = await _supabaseClient
              .from(table)
              .select('user_id')
              .eq('user_id', user.id)
              .maybeSingle();
              
          if (profileCheck == null) {
            await _supabaseClient.auth.signOut();
            state = AsyncValue.error('User does not exist. Please create a new account.', StackTrace.current);
            return false;
          }
        } catch (e) {
          debugPrint('Warning: Could not verify profile existence: $e');
          // If network error, we might still let them in if offline, but since signInWithPassword succeeded, they are online.
        }

        state = AsyncValue.data(authResponse);

        // --- ADDED THIS WAKE-UP CALL FOR POWERSYNC ---
        try {
          DatabaseManager.powersync.connect(
              connector: SupabaseConnector(
                supabase: _supabaseClient,
                powerSyncUrl: EnvConfig.powerSyncUrl,
              )
          );
          debugPrint('🟢 PowerSync manual connect triggered after login.');
        } catch (e) {
          debugPrint('🔴 Failed to trigger PowerSync connect: $e');
        }
        // ---------------------------------------------

        return true;
      } else {
        state = AsyncValue.error('Unknown login error occurred.', StackTrace.current);
        return false;
      }

    } catch (e) {
      state = AsyncValue.error(ErrorHelper.getHumanReadableError(e), StackTrace.current);
      return false;
    }
  }

  // ==========================================
  // 2. LIVE LOGOUT LOGIC
  // ==========================================
  Future<void> logout() async {
    state = const AsyncValue.loading();
    await _supabaseClient.auth.signOut();

    // Optional but recommended: Tell PowerSync to disconnect when logging out
    try {
      await DatabaseManager.powersync.disconnect();
    } catch (e) {
      debugPrint('PowerSync disconnect error: $e');
    }

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
          emailRedirectTo: 'mediscanx://login',
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

      // Debug: print raw response to help diagnose email delivery problems
      debugPrint('🔔 signUp response: $response');

      final user = (response as dynamic).user;

      if (user != null) {
        // If 'prevent email enumeration' is on, Supabase returns a user but with an empty identities array
        // if the email already exists.
        if (user.identities != null && user.identities!.isEmpty) {
          state = AsyncValue.error('Email is already registered. Please log in instead.', StackTrace.current);
          return false;
        }

        state = AsyncValue.data(
          AuthResponse(
            success: true,
            message: 'Check your email to verify your account before signing in.',
            userId: user.id,
            userType: normalizedRole,
            fullName: request.fullName,
            gender: request.gender,
            age: null,
          ),
        );
        return true;
      }

      // Some Supabase configurations (email confirmation enabled) return no
      // immediate user and expect the user to confirm via email. Treat that as
      // a successful signup that requires verification.
      try {
        // If response doesn't include a user, assume confirmation email was sent.
        state = AsyncValue.data(
          AuthResponse(
            success: true,
            message: 'Confirmation email sent. Check your inbox (and spam).',
            userId: null,
            userType: normalizedRole,
            fullName: request.fullName,
            gender: request.gender,
            age: null,
          ),
        );
        return true;
      } catch (e) {
        state = AsyncValue.error('Signup failed. Please try again.', StackTrace.current);
        return false;
      }
    } catch (e) {
      state = AsyncValue.error(ErrorHelper.getHumanReadableError(e), StackTrace.current);
      return false;
    }
  }

  Future<bool> resendConfirmationEmail(String email) async {
    state = const AsyncValue.loading();
    try {
      await _supabaseClient.auth.resend(
        email: email,
        type: supabase.OtpType.signup,
        emailRedirectTo: 'mediscanx://login',
      );
      state = const AsyncValue.data(null);
      return true;
    } catch (e) {
      state = AsyncValue.error(ErrorHelper.getHumanReadableError(e), StackTrace.current);
      return false;
    }
  }

  // Verify the 6-digit code for new signups
  Future<bool> verifySignupCode(String email, String code) async {
    state = const AsyncValue.loading();
    try {
      await _supabaseClient.auth.verifyOTP(
        type: supabase.OtpType.signup,
        email: email,
        token: code,
      );
      state = const AsyncValue.data(null);
      return true;
    } catch (e) {
      state = AsyncValue.error(ErrorHelper.getHumanReadableError(e), StackTrace.current);
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
      await _supabaseClient.auth.resetPasswordForEmail(
        email,
        redirectTo: 'mediscanx://password-reset',
      );
      state = const AsyncValue.data(null);
      return true;
    } catch (e) {
      state = AsyncValue.error(ErrorHelper.getHumanReadableError(e), StackTrace.current);
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
    } catch (e) {
      state = AsyncValue.error(ErrorHelper.getHumanReadableError(e), StackTrace.current);
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
    } catch (e) {
      state = AsyncValue.error(ErrorHelper.getHumanReadableError(e), StackTrace.current);
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
  final notifier =  AuthStateNotifier();

  // Trigger the offline validation check immediately
  notifier.initialize();

  return notifier;
});