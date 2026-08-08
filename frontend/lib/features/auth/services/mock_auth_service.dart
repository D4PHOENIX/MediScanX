import '../models/auth_models.dart';

/// Mock Authentication Service - For development
/// Replace with Firebase later
class MockAuthService {
  // Simulated user database
  static final Map<String, Map<String, String>> _userDatabase = {
    'demo@mediscanx.com': {
      'password': 'Demo@123',
      'fullName': 'Demo User',
      'email': 'demo@mediscanx.com',
      'userType': 'patient',
    },
  };

  // Simulated reset codes (in production, this would be sent via email)
  static final Map<String, String> _resetCodes = {};

  /// Login with email and password
  Future<AuthResponse> login(LoginRequest request) async {
    // Simulate network delay
    await Future.delayed(const Duration(milliseconds: 1500));

    try {
      final user = _userDatabase[request.username];

      if (user == null) {
        return AuthResponse(
          success: false,
          message:
          'No user account found with this username. Please check your username or create a new account.',
        );
      }

      if (user['password'] != request.password) {
        return AuthResponse(
          success: false,
          message:
          'Incorrect password. Please check your password and try again.',
        );
      }

      return AuthResponse(
        success: true,
        message: 'Login successful',
        token: 'mock_token_${DateTime.now().millisecondsSinceEpoch}',
        userId: 'user_${request.username.hashCode}',
        userType: user['userType'],
      );
    } catch (e) {
      return AuthResponse(
        success: false,
        message: 'An unexpected error occurred. Please try again.',
      );
    }
  }

  /// Sign up new user
  Future<AuthResponse> signup(SignupRequest request) async {
    // Simulate network delay
    await Future.delayed(const Duration(milliseconds: 1500));

    try {
      // Check if email already exists
      if (_userDatabase.containsKey(request.username)) {
        return AuthResponse(
          success: false,
          message:
          'Email already registered. Please sign in or use a different email.',
        );
      }

      // Validate inputs
      if (request.fullName.isEmpty) {
        return AuthResponse(
          success: false,
          message: 'Full name is required',
        );
      }

      if (request.password.length < 6) {
        return AuthResponse(
          success: false,
          message: 'Password must be at least 6 characters',
        );
      }

      // Add user to database
      _userDatabase[request.username] = {
        'password': request.password,
        'fullName': request.fullName,
        'email': request.email,
        'userType': request.userType,
        'phoneNumber': request.phoneNumber,
        'gender': request.gender ?? '',
        'dateOfBirth': request.dateOfBirth ?? '',
        'location': request.location ?? '',
        'specialization': request.specialization ?? '',
        'currentHospital': request.currentHospital ?? '',
      };

      return AuthResponse(
        success: true,
        message: 'Account created successfully. Please verify your email.',
        token: 'mock_token_${DateTime.now().millisecondsSinceEpoch}',
        userId: 'user_${request.username.hashCode}',
        userType: request.userType,
      );
    } catch (e) {
      return AuthResponse(
        success: false,
        message: 'An unexpected error occurred. Please try again.',
      );
    }
  }

  /// Request password reset
  Future<AuthResponse> resetPassword(PasswordResetRequest request) async {
    // Simulate network delay
    await Future.delayed(const Duration(milliseconds: 1500));

    try {
      if (!_userDatabase.containsKey(request.username)) {
        return AuthResponse(
          success: false,
          message:
          'No account found with this username. Please check and try again.',
        );
      }

      // Generate a mock reset code
      final resetCode = '${DateTime.now().millisecond}'.padLeft(6, '0').substring(0, 6);
      _resetCodes[request.username] = resetCode;

      // In production, this code would be sent via email
      print('Mock Reset Code for ${request.username}: $resetCode');

      return AuthResponse(
        success: true,
        message:
        'Password reset instructions sent to your email. Please check your inbox.',
      );
    } catch (e) {
      return AuthResponse(
        success: false,
        message: 'An unexpected error occurred. Please try again.',
      );
    }
  }

  /// Verify reset code
  Future<AuthResponse> verifyResetCode(VerifyResetCodeRequest request) async {
    // Simulate network delay
    await Future.delayed(const Duration(milliseconds: 1500));

    try {
      final storedCode = _resetCodes[request.username];

      if (storedCode == null) {
        return AuthResponse(
          success: false,
          message: 'Please request a password reset first.',
        );
      }

      // For demo purposes, accept code "000000" as valid
      if (request.code != storedCode && request.code != '000000') {
        return AuthResponse(
          success: false,
          message:
          'Invalid reset code. Please check the code sent to your email.',
        );
      }

      return AuthResponse(
        success: true,
        message: 'Code verified successfully. Please set your new password.',
      );
    } catch (e) {
      return AuthResponse(
        success: false,
        message: 'An unexpected error occurred. Please try again.',
      );
    }
  }

  /// Confirm new password
  Future<AuthResponse> confirmNewPassword(
      ConfirmNewPasswordRequest request,
      ) async {
    // Simulate network delay
    await Future.delayed(const Duration(milliseconds: 1500));

    try {
      if (request.newPassword != request.confirmPassword) {
        return AuthResponse(
          success: false,
          message: 'Passwords do not match.',
        );
      }

      if (request.newPassword.length < 6) {
        return AuthResponse(
          success: false,
          message: 'Password must be at least 6 characters.',
        );
      }

      final user = _userDatabase[request.username];
      if (user == null) {
        return AuthResponse(
          success: false,
          message: 'User not found.',
        );
      }

      // Update password in database
      user['password'] = request.newPassword;

      // Clear the reset code
      _resetCodes.remove(request.username);

      return AuthResponse(
        success: true,
        message: 'Password reset successfully. Please sign in with your new password.',
      );
    } catch (e) {
      return AuthResponse(
        success: false,
        message: 'An unexpected error occurred. Please try again.',
      );
    }
  }
}