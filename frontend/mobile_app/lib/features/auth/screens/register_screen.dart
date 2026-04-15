
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart'; // NEW: Live Supabase import

import '../../../core/themes/app_colors.dart';
import '../../../core/themes/app_typography.dart';
import '../../../core/utils/validators.dart';
import '../../../shared/widgets/custom_input_field.dart';
import '../../../shared/widgets/custom_button.dart';
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

  // UI State
  String _userType = 'patient';
  String? _selectedGender;
  bool _obscurePassword = true;
  bool _isLoading = false; // NEW: Local loading state

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
  }

  @override
  void dispose() {
    _fullNameController.dispose();
    _usernameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _phoneNumberController.dispose();
    _dateOfBirthController.dispose();
    _locationController.dispose();
    _hospitalController.dispose();
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
        // THE FIX: Pack ALL the data into the Supabase signUp request!
        // The backend trigger will catch this and create the public profiles automatically.
        await Supabase.instance.client.auth.signUp(
          email: _emailController.text.trim(),
          password: _passwordController.text,
          data: {
            'full_name': _fullNameController.text.trim(),
            'username': _usernameController.text.trim(),
            'role': _userType == 'doctor' ? 'Doctor' : 'Patient', // Tell backend the role
            'gender': _selectedGender,
            'date_of_birth': _dateOfBirthController.text.trim(),
            'phone_number': _phoneNumberController.text.trim(),
            'location': _locationController.text.trim(),
            // Doctor specific fields (will be null for patients, which is fine)
            'specialization': _selectedSpecialization,
            'current_hospital': _hospitalController.text.trim(),
          },
        );

        // NOTICE: We completely deleted the db.execute() blocks!
        // Because PowerSync is active, the moment the backend trigger creates the row
        // in Supabase, PowerSync will automatically download it to the device in the background.

        // GoRouter will automatically detect the Supabase session and route to the dashboard!

      } on AuthException catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Registration Error: ${e.message}', style: const TextStyle(color: Colors.white)), backgroundColor: Colors.red),
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('App Error: $e', style: const TextStyle(color: Colors.white)), backgroundColor: Colors.red),
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

  @override
  Widget build(BuildContext context) {
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
                  Image.asset('assets/images/logo_icon.png', height: 72),
                  const SizedBox(height: 12),
                  Text('MediScanX', style: AppTypography.headlineM.copyWith(color: AppColors.primaryBlue)),
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
                        child: CustomInputField(
                            label: 'Date of Birth *', hint: 'YYYY-MM-DD',
                            controller: _dateOfBirthController,
                            keyboardType: TextInputType.datetime,
                            errorText: _dateOfBirthError
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
                          value: _selectedSpecialization,
                          hint: Text('Select Specialization', style: AppTypography.bodyS),
                          decoration: InputDecoration(
                            prefixIcon: const Icon(Icons.medical_services_outlined, size: 20, color: AppColors.primaryBlue),
                            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                            enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: AppColors.textLight.withOpacity(0.3))),
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