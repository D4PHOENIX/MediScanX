
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart'; // Added Supabase import
import '../../../core/themes/app_colors.dart';
import '../../../core/themes/app_typography.dart';
import '../../../shared/widgets/custom_input_field.dart';
import '../../../shared/widgets/custom_button.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({Key? key}) : super(key: key);

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  late TextEditingController _usernameController;
  late TextEditingController _passwordController;
  bool _obscurePassword = true;

  // Local state for loading and errors
  bool _isLoading = false;
  String? _loginError;

  String? _usernameError;
  String? _passwordError;

  @override
  void initState() {
    super.initState();
    _usernameController = TextEditingController();
    _passwordController = TextEditingController();
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _validateFields() {
    setState(() {
      _usernameError = _usernameController.text.trim().isEmpty
          ? 'Username or Email is required'
          : null;

      if (_passwordController.text.isEmpty) {
        _passwordError = 'Password is required';
      } else if (_passwordController.text.length < 6) {
        _passwordError = 'Password must be at least 6 characters';
      } else {
        _passwordError = null;
      }
    });
  }

  Future<void> _handleLogin() async {
    _validateFields();

    if (_usernameError == null && _passwordError == null) {
      setState(() {
        _isLoading = true;
        _loginError = null;
      });

      try {
        // Live Supabase Authentication
        await Supabase.instance.client.auth.signInWithPassword(
          email: _usernameController.text.trim(),
          password: _passwordController.text,
        );

        // Note: We do NOT need context.goNamed('dashboard') here!
        // The GoRouterRefreshStream in your main.dart will automatically
        // detect the new session and instantly route you to the dashboard.

      } on AuthException catch (e) {
        setState(() {
          _loginError = e.message; // Catch specific Supabase errors (e.g. Invalid credentials)
        });
      } catch (e) {
        setState(() {
          _loginError = 'An unexpected error occurred. Please try again.';
        });
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
          // Watermark Background
          Positioned(
            top: 150,
            right: -80,
            child: Opacity(
              opacity: 0.1,
              child: Image.asset(
                'assets/images/lungs_watermark.png',
                width: 450,
                errorBuilder: (context, error, stackTrace) => const Icon(
                  Icons.medical_services_outlined,
                  size: 450,
                  color: AppColors.primaryBlue,
                ),
              ),
            ),
          ),

          SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  // Brand Logo
                  Image.asset(
                    'assets/images/logo_icon.png',
                    height: 72,
                    errorBuilder: (context, error, stackTrace) => Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: AppColors.primaryBlue,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Icon(Icons.medical_services,
                          color: Colors.white, size: 28),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'MediScanX',
                    style: AppTypography.headlineM.copyWith(
                      color: AppColors.primaryBlue,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'AI-Powered Medical Triage Platform',
                    style: AppTypography.bodyS.copyWith(
                      color: AppColors.textLight,
                    ),
                  ),
                  const SizedBox(height: 32),

                  Text(
                    'Welcome back',
                    style: AppTypography.headlineS,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Sign in to access your dashboard and patient records',
                    textAlign: TextAlign.center,
                    style: AppTypography.bodyS.copyWith(
                      color: AppColors.textLight,
                    ),
                  ),
                  const SizedBox(height: 32),

                  // Dynamic Error Banner
                  if (_loginError != null) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.red.withOpacity(0.1),
                        border: Border.all(color: Colors.red.withOpacity(0.3)),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.error_outline,
                              color: Colors.red, size: 20),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              _loginError!,
                              style: AppTypography.bodyS
                                  .copyWith(color: Colors.red),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 24),
                  ],

                  // Credentials Input
                  CustomInputField(
                    label: 'Email Address',
                    hint: 'Enter your email address',
                    controller: _usernameController,
                    keyboardType: TextInputType.emailAddress,
                    errorText: _usernameError,
                    prefixIcon: Icon(
                      Icons.person_outline,
                      color: AppColors.textLight.withOpacity(0.6),
                      size: 20,
                    ),
                  ),
                  const SizedBox(height: 20),

                  CustomInputField(
                    label: 'Password',
                    hint: 'Enter your password',
                    controller: _passwordController,
                    obscureText: _obscurePassword,
                    errorText: _passwordError,
                    prefixIcon: Icon(
                      Icons.lock_outline,
                      color: AppColors.textLight.withOpacity(0.6),
                      size: 20,
                    ),
                    suffixIcon: IconButton(
                      icon: Icon(
                        _obscurePassword
                            ? Icons.visibility_off_outlined
                            : Icons.visibility_outlined,
                        color: AppColors.textLight.withOpacity(0.6),
                        size: 20,
                      ),
                      onPressed: () {
                        setState(() {
                          _obscurePassword = !_obscurePassword;
                        });
                      },
                    ),
                  ),

                  // Forgot Password Button
                  Align(
                    alignment: Alignment.centerRight,
                    child: Padding(
                      padding: const EdgeInsets.only(top: 8.0),
                      child: InkWell(
                        onTap: () => context.pushNamed('password-reset'),
                        borderRadius: BorderRadius.circular(4),
                        child: Padding(
                          padding: const EdgeInsets.all(4.0),
                          child: Text(
                            'Forgot password?',
                            style: AppTypography.bodyS.copyWith(
                              color: AppColors.accentCyan,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),

                  // Action Button
                  CustomButton(
                    label: 'Sign In',
                    isLoading: _isLoading,
                    onPressed: _handleLogin,
                  ),
                  const SizedBox(height: 24),

                  // Footer Links
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        'New to MediScanX? ',
                        style: AppTypography.bodyM.copyWith(
                          color: AppColors.textLight,
                        ),
                      ),
                      GestureDetector(
                        onTap: () => context.pushNamed('register'),
                        child: Text(
                          'Create an Account',
                          style: AppTypography.bodyM.copyWith(
                            color: AppColors.primaryBlue,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}