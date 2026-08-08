class LoginRequest {
  final String username;
  final String password;

  LoginRequest({
    required this.username,
    required this.password,
  });
}

class SignupRequest {
  final String fullName;
  final String username;
  final String email;
  final String password;
  final String phoneNumber;
  final String userType;
  final String? gender;
  final String? dateOfBirth;
  final String? location;
  final String? specialization;
  final String? currentHospital;

  SignupRequest({
    required this.fullName,
    required this.username,
    required this.email,
    required this.password,
    required this.phoneNumber,
    required this.userType,
    this.gender,
    this.dateOfBirth,
    this.location,
    this.specialization,
    this.currentHospital,
  });
}

class PasswordResetRequest {
  final String username;

  PasswordResetRequest({required this.username});
}

class VerifyResetCodeRequest {
  final String username;
  final String code;

  VerifyResetCodeRequest({
    required this.username,
    required this.code,
  });
}

class ConfirmNewPasswordRequest {
  final String username;
  final String code;
  final String newPassword;
  final String confirmPassword;

  ConfirmNewPasswordRequest({
    required this.username,
    required this.code,
    required this.newPassword,
    required this.confirmPassword,
  });
}

class AuthResponse {
  final bool success;
  final String message;
  final String? token;
  final String? userId;
  final String? userType;
  final String? fullName;
  final String? gender;
  final int? age;

  AuthResponse({
    required this.success,
    required this.message,
    this.token,
    this.userId,
    this.userType,
    this.fullName,
    this.gender,
    this.age,
  });
}