
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../../core/themes/app_colors.dart';
import '../../../core/themes/app_typography.dart';
import '../../../core/utils/validators.dart';
import '../models/auth_models.dart';
import '../providers/auth_state_provider.dart';
import '../../../core/themes/app_typography.dart';
import 'package:mediscanx_mobile/core/themes/app_typography.dart';
import 'package:mediscanx_mobile/core/utils/error_helper.dart';
import '../../../shared/widgets/custom_input_field.dart';
import '../../../shared/widgets/custom_button.dart';
import '../../../main.dart';
import '../../../shared/widgets/user_type_toggle.dart';
import '../../../shared/widgets/gender_selector.dart';

class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({Key? key}) : super(key: key);

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  // Controllers
  late TextEditingController _fullNameController;
  late TextEditingController _usernameController;
  late TextEditingController _emailController;
  late TextEditingController _passwordController;
  late TextEditingController _phoneNumberController;
  late TextEditingController _dateOfBirthController;
  late TextEditingController _locationController;
  late TextEditingController _hospitalController;
  late TextEditingController _otpController;

  // UI State
  String _userType = 'patient';
  String? _selectedGender;
  bool _obscurePassword = true;
  bool _isLoading = false; 
  bool _confirmationSent = false;
  String? _confirmationEmail;
  bool _isResendingConfirmation = false;
  bool _isVerifyingOtp = false; // NEW: Verify loading state
  StreamSubscription<dynamic>? _authSubscription;

  // Dropdown State
  String? _selectedSpecialization;
  final List<String> _specializationCategories = [
    'Cardiologist',
    'Dermatologist',
    'Radiologist',
  ];

  // Error States
  String? _fullNameError, _usernameError, _emailError, _passwordError,
      _phoneNumberError, _dateOfBirthError, _locationError, _genderError,
      _specError, _hospitalError;

  @override
  void initState() {
    super.initState();
    _fullNameController = TextEditingController();
    _usernameController = TextEditingController();
    _emailController = TextEditingController();
    _passwordController = TextEditingController();
    _phoneNumberController = TextEditingController();
    _dateOfBirthController = TextEditingController();
    _locationController = TextEditingController();
    _hospitalController = TextEditingController();
    _otpController = TextEditingController();
    _initializeConfirmationListener();
  }

  Future<void> _handleVerifyOtp() async {
    final code = _otpController.text.trim();
    if (code.isEmpty || code.length < 6 || code.length > 8) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter a valid verification code.'), backgroundColor: Colors.red),
      );
      return;
    }

    setState(() => _isVerifyingOtp = true);
    try {
      final success = await ref.read(authStateProvider.notifier).verifySignupCode(_confirmationEmail!, code);
      if (success && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Account verified successfully! Please sign in.'), backgroundColor: Colors.green),
        );
        context.goNamed('login');
      } else if (mounted) {
        final error = ref.read(authStateProvider).error?.toString() ?? 'Invalid or expired code.';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isVerifyingOtp = false);
      }
    }
  }

  void _initializeConfirmationListener() {
    try {
      _authSubscription = Supabase.instance.client.auth.onAuthStateChange.listen((event) async {
        try {
          final ev = (event as dynamic);
          debugPrint('🔐 RegisterScreen: AuthState changed - ${ev.event}');

          if (!_confirmationSent || !mounted) return;

          final session = Supabase.instance.client.auth.currentSession;
          if (session != null) {
            debugPrint('🔐 RegisterScreen: Email verified, auto-navigating to login');
            await Supabase.instance.client.auth.signOut();
            if (mounted) {
              context.goNamed('login');
            }
          }
        } catch (e) {
          debugPrint('❌ RegisterScreen: Unexpected auth payload: $e');
        }
      });
    } catch (e) {
      debugPrint('❌ RegisterScreen: Listener init error: $e');
    }
  }

  Future<void> _pickDateOfBirth() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: DateTime(2000, 1, 1),
      firstDate: DateTime(1950),
      lastDate: now,
      helpText: 'SELECT DATE OF BIRTH',
      builder: (context, child) {
        return Theme(
          data: Theme.of(context).copyWith(
            colorScheme: const ColorScheme.light(
              primary: AppColors.primaryBlue,
              onPrimary: Colors.white,
              surface: Colors.white,
              onSurface: AppColors.textDark,
            ),
          ),
          child: child!,
        );
      },
    );

    if (picked != null) {
      final formatted =
          '${picked.year}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
      setState(() {
        _dateOfBirthController.text = formatted;
        _dateOfBirthError = null; // Clear error on valid selection
      });
    }
  }

  @override
  void dispose() {
    _authSubscription?.cancel();
    _fullNameController.dispose();
    _usernameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _phoneNumberController.dispose();
    _dateOfBirthController.dispose();
    _locationController.dispose();
    _hospitalController.dispose();
    _otpController.dispose();
    super.dispose();
  }

  Future<void> _handleSignup() async {
    setState(() {
      _fullNameError = AppValidators.validateFullName(_fullNameController.text);
      _usernameError = AppValidators.validateUsername(_usernameController.text);
      _emailError = AppValidators.validateEmail(_emailController.text);
      _passwordError = AppValidators.validatePassword(_passwordController.text);
      _phoneNumberError = AppValidators.validatePhoneNumber(_phoneNumberController.text);
      _locationError = AppValidators.validateLocation(_locationController.text);
      _dateOfBirthError = AppValidators.validateDateOfBirth(_dateOfBirthController.text);
      _genderError = _selectedGender == null ? 'Please select gender' : null;

      if (_userType == 'doctor') {
        _specError = _selectedSpecialization == null ? 'Specialization is required' : null;
        _hospitalError = AppValidators.validateProfessionalField(_hospitalController.text, 'Hospital');
      } else {
        _specError = null;
        _hospitalError = null;
      }
    });

    if (_fullNameError == null && _usernameError == null && _emailError == null &&
        _passwordError == null && _phoneNumberError == null && _dateOfBirthError == null &&
        _locationError == null && _genderError == null &&
        _specError == null && _hospitalError == null) {

      setState(() {
        _isLoading = true;
      });

      try {
        // Suppress automatic navigation just in case
        armLoginRedirectSuppression();
        
        final success = await ref.read(authStateProvider.notifier).signup(
          SignupRequest(
            fullName: _fullNameController.text.trim(),
            username: _usernameController.text.trim(),
            email: _emailController.text.trim(),
            password: _passwordController.text,
            phoneNumber: _phoneNumberController.text.trim(),
            userType: _userType,
            gender: _selectedGender,
            dateOfBirth: _dateOfBirthController.text.trim(),
            location: _locationController.text.trim(),
            specialization: _selectedSpecialization,
            currentHospital: _hospitalController.text.trim(),
          ),
        );

        if (success && mounted) {
          final session = Supabase.instance.client.auth.currentSession;
          if (session != null) {
             // Email confirmations are disabled on Supabase, so they are already logged in!
             // Just take them straight to the dashboard.
             context.goNamed('dashboard');
          } else {
             // Email confirmation is required
             setState(() {
               _confirmationSent = true;
               _confirmationEmail = _emailController.text.trim();
             });
          }
        } else if (!success && mounted) {
          final errorMsg = ref.read(authStateProvider).error?.toString() ?? 'Signup failed.';
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(errorMsg, style: const TextStyle(color: Colors.white)), backgroundColor: Colors.red),
          );
        }

      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(ErrorHelper.getHumanReadableError(e), style: const TextStyle(color: Colors.white)), backgroundColor: Colors.red),
          );
        }
      } finally {
        if (mounted) {
          setState(() {
            _isLoading = false;
          });
        }
      }
    }
  }

  Future<void> _handleResendConfirmation() async {
    final email = _confirmationEmail;
    if (email == null || email.isEmpty) {
      return;
    }

    setState(() => _isResendingConfirmation = true);
    try {
      final success = await ref.read(authStateProvider.notifier).resendConfirmationEmail(email);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              success
                  ? 'Confirmation email resent. Please check your inbox.'
                  : 'Could not resend confirmation email.',
            ),
            backgroundColor: success ? Colors.green : Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isResendingConfirmation = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_confirmationSent) {
      return Scaffold(
        backgroundColor: AppColors.neutralBackground,
        body: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.mark_email_read_outlined, color: AppColors.accentCyan, size: 96),
                  const SizedBox(height: 20),
                  Text('Verify Your Email', style: AppTypography.headlineS),
                  const SizedBox(height: 16),
                  Text(
                    'We sent a 8-digit confirmation code to $_confirmationEmail. Please enter it below to verify your account.',
                    textAlign: TextAlign.center,
                    style: AppTypography.bodyS.copyWith(color: AppColors.textLight),
                  ),
                  const SizedBox(height: 32),
                  CustomInputField(
                    label: 'Verification Code',
                    hint: '12345678',
                    controller: _otpController,
                    keyboardType: TextInputType.number,
                  ),
                  const SizedBox(height: 24),
                  CustomButton(
                    label: 'VERIFY CODE',
                    isLoading: _isVerifyingOtp,
                    onPressed: _handleVerifyOtp,
                  ),
                  const SizedBox(height: 16),
                  TextButton(
                    onPressed: _isResendingConfirmation ? null : _handleResendConfirmation,
                    child: _isResendingConfirmation
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Resend confirmation code'),
                  ),
                ],
                ),
              ),
            ),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: AppColors.neutralBackground,
      body: Stack(
        fit: StackFit.expand,
        children: [
          Positioned(
            top: 150, right: -80,
            child: Opacity(
              opacity: 0.1,
              child: Image.asset('assets/images/lungs_watermark.png', width: 450),
            ),
          ),

          SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                children: [
                  Row(
                    children: [
                      if (context.canPop())
                        GestureDetector(
                          onTap: () => context.pop(),
                          child: Container(
                            margin: const EdgeInsets.only(right: 12),
                            padding: const EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: Colors.white,
                              borderRadius: BorderRadius.circular(12),
                              boxShadow: [BoxShadow(color: AppColors.primaryBlue.withOpacity(0.08), blurRadius: 8, offset: const Offset(0, 2))],
                            ),
                            child: const Icon(Icons.arrow_back_ios_new_rounded, size: 16, color: AppColors.primaryBlue),
                          ),
                        ),
                      Expanded(
                        child: Center(
                          child: Image.asset('assets/images/logo_icon.png', height: 72),
                        ),
                      ),
                      if (context.canPop()) const SizedBox(width: 44), // To balance the back button
                    ],
                  ),
                  const SizedBox(height: 12),
                  Center(child: Text('MediScanX', style: AppTypography.headlineM.copyWith(color: AppColors.primaryBlue))),
                  const SizedBox(height: 24),

                  UserTypeToggle(
                    selectedType: _userType,
                    onChanged: (val) => setState(() => _userType = val.toLowerCase()),
                  ),
                  const SizedBox(height: 32),

                  Align(
                    alignment: Alignment.centerLeft,
                    child: Text('PERSONAL DETAILS', style: AppTypography.labelS.copyWith(color: AppColors.accentCyan, letterSpacing: 1.1)),
                  ),
                  const SizedBox(height: 20),

                  CustomInputField(label: 'Full Name *', hint: 'Letters only', controller: _fullNameController, errorText: _fullNameError),
                  const SizedBox(height: 16),
                  CustomInputField(label: 'Username *', hint: 'Letters + Numbers (e.g. amir786)', controller: _usernameController, errorText: _usernameError),
                  const SizedBox(height: 16),
                  CustomInputField(label: 'Email *', hint: 'amir786@gmail.com', controller: _emailController, errorText: _emailError),
                  const SizedBox(height: 16),

                  CustomInputField(
                    label: 'Password *', hint: 'Min. 6 characters', controller: _passwordController,
                    obscureText: _obscurePassword, errorText: _passwordError,
                    suffixIcon: IconButton(
                      icon: Icon(_obscurePassword ? Icons.visibility_off : Icons.visibility),
                      onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
                    ),
                  ),
                  const SizedBox(height: 16),
                  CustomInputField(
                      label: 'Phone *', hint: 'Numbers only', controller: _phoneNumberController,
                      keyboardType: TextInputType.number, errorText: _phoneNumberError
                  ),
                  const SizedBox(height: 16),
                  CustomInputField(label: 'Location *', hint: 'Letters only', controller: _locationController, errorText: _locationError),
                  const SizedBox(height: 16),

                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: GestureDetector(
                          onTap: () => _pickDateOfBirth(),
                          child: AbsorbPointer(
                            child: CustomInputField(
                              label: 'Date of Birth *',
                              hint: 'YYYY-MM-DD',
                              controller: _dateOfBirthController,
                              keyboardType: TextInputType.datetime,
                              errorText: _dateOfBirthError,
                              suffixIcon: IconButton(
                                icon: const Icon(Icons.calendar_month_rounded, color: AppColors.primaryBlue),
                                onPressed: () => _pickDateOfBirth(),
                              ),
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Gender *', style: AppTypography.labelM),
                            const SizedBox(height: 8),
                            GenderSelector(selectedGender: _selectedGender, onChanged: (val) => setState(() => _selectedGender = val)),
                            if (_genderError != null) Padding(
                              padding: const EdgeInsets.only(top: 8.0),
                              child: Text(_genderError!, style: const TextStyle(color: Colors.red, fontSize: 12)),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),

                  // DOCTOR PANEL
                  if (_userType == 'doctor') ...[
                    const Padding(padding: EdgeInsets.symmetric(vertical: 24.0), child: Divider()),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Text('PROFESSIONAL DETAILS', style: AppTypography.labelS.copyWith(color: AppColors.accentCyan, letterSpacing: 1.1)),
                    ),
                    const SizedBox(height: 16),

                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Specialization *', style: AppTypography.labelM.copyWith(fontSize: 12, color: AppColors.textLight)),
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          initialValue: _selectedSpecialization,
                          hint: Text('Select Specialization', style: AppTypography.bodyS),
                          decoration: InputDecoration(
                            prefixIcon: const Icon(Icons.medical_services_outlined, size: 20, color: AppColors.primaryBlue),
                            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                            enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: AppColors.textLight.withValues(alpha: 0.3))),
                            errorText: _specError,
                            filled: true,
                            fillColor: Colors.white,
                          ),
                          items: _specializationCategories.map((String category) {
                            return DropdownMenuItem<String>(
                              value: category,
                              child: Text(category, style: AppTypography.bodyM),
                            );
                          }).toList(),
                          onChanged: (val) {
                            setState(() {
                              _selectedSpecialization = val;
                              _specError = null;
                            });
                          },
                        ),
                      ],
                    ),

                    const SizedBox(height: 16),
                    CustomInputField(
                      label: 'Current Hospital *',
                      hint: 'Letters only',
                      controller: _hospitalController,
                      errorText: _hospitalError,
                      prefixIcon: const Icon(Icons.local_hospital_outlined, size: 20),
                    ),
                  ],

                  const SizedBox(height: 40),

                  CustomButton(
                      label: 'Create ${_userType.toUpperCase()} Account',
                      isLoading: _isLoading,
                      onPressed: _handleSignup
                  ),
                  const SizedBox(height: 24),

                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text('Already have an account? ', style: AppTypography.bodyS),
                      GestureDetector(
                        onTap: () => context.goNamed('login'),
                        child: Text(
                            'Sign In',
                            style: AppTypography.bodyS.copyWith(color: AppColors.primaryBlue, fontWeight: FontWeight.bold)
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 40),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}