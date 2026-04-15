// lib/core/utils/validators.dart

class AppValidators {
  /// 1. Full Name: Strictly letters and spaces only
  static String? validateFullName(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Full Name is required';
    }
    // Regex for letters and spaces only
    final nameRegExp = RegExp(r"^[a-zA-Z\s]+$");
    if (!nameRegExp.hasMatch(value.trim())) {
      return 'Letters only (no numbers or symbols)';
    }
    return null;
  }

  /// 2. Username: Mix of Strings and Integers
  static String? validateUsername(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Username is required';
    }
    // Ensures at least one letter AND at least one number
    final userRegExp = RegExp(r'^(?=.*[a-zA-Z])(?=.*[0-9])[a-zA-Z0-9_]+$');
    if (!userRegExp.hasMatch(value.trim())) {
      return 'Use a mix of letters and numbers';
    }
    return null;
  }

  /// 3. Email: Standard Email format check
  static String? validateEmail(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Email address is required';
    }
    final emailRegExp = RegExp(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$');
    if (!emailRegExp.hasMatch(value.trim())) {
      return 'Please enter a valid email address';
    }
    return null;
  }

  /// 4. Password: Minimum length check
  static String? validatePassword(String? value) {
    if (value == null || value.isEmpty) {
      return 'Password is required';
    }
    if (value.length < 6) {
      return 'Password must be at least 6 characters';
    }
    return null;
  }

  /// 5. Phone Number: Strictly numeric
  static String? validatePhoneNumber(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Phone number is required';
    }
    // Checks if the string can be parsed as a number
    if (int.tryParse(value.trim()) == null) {
      return 'Enter valid numbers only';
    }
    return null;
  }

  /// 6. Location: Strictly String values
  static String? validateLocation(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Location is required';
    }
    // Rejects if any digit (0-9) is found
    if (RegExp(r'[0-9]').hasMatch(value)) {
      return 'Letters only (no numbers)';
    }
    return null;
  }

  /// 7. Age: Strictly numeric (1-120 range)
  static String? validateAge(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Age is required';
    }
    final ageVal = int.tryParse(value.trim());
    if (ageVal == null) {
      return 'Numbers only';
    }
    if (ageVal < 1 || ageVal > 120) {
      return 'Enter a valid age (1-120)';
    }
    return null;
  }

  /// 7b. Date of Birth: ISO date (YYYY-MM-DD) and realistic age range.
  static String? validateDateOfBirth(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Date of birth is required';
    }

    final dob = DateTime.tryParse(value.trim());
    if (dob == null) {
      return 'Use YYYY-MM-DD format';
    }

    final today = DateTime.now();
    if (dob.isAfter(today)) {
      return 'Date of birth cannot be in the future';
    }

    var age = today.year - dob.year;
    if (today.month < dob.month ||
        (today.month == dob.month && today.day < dob.day)) {
      age--;
    }

    if (age < 1 || age > 120) {
      return 'Enter a valid date of birth';
    }

    return null;
  }

  /// 8. Professional Fields: Specialization/Hospital (String only)
  static String? validateProfessionalField(String? value, String fieldName) {
    if (value == null || value.trim().isEmpty) {
      return '$fieldName is required';
    }
    // Rejects if any digit is found
    if (RegExp(r'[0-9]').hasMatch(value)) {
      return 'Letters only (no numbers)';
    }
    return null;
  }
}