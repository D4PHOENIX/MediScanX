import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../../../core/themes/app_colors.dart';
import '../../../core/themes/app_typography.dart';
import '../../../core/utils/validators.dart';
import '../../../shared/widgets/custom_input_field.dart';
import '../../../shared/widgets/custom_button.dart';
import '../providers/auth_state_provider.dart';

class PasswordResetScreen extends ConsumerStatefulWidget {
  const PasswordResetScreen({Key? key}) : super(key: key);
  @override
  ConsumerState<PasswordResetScreen> createState() => _PasswordResetScreenState();
}

class _PasswordResetScreenState extends ConsumerState<PasswordResetScreen> {
  final _emailController = TextEditingController();
  final _newPassController = TextEditingController();
  final _confirmPassController = TextEditingController();

  String? _eEmail, _eNew, _eConfirm;
  bool _emailSent = false;
  bool _recoveryReady = false;
  bool _obs1 = true;
  bool _obs2 = true;
  late final StreamSubscription<AuthState> _authSubscription;

  @override
  void initState() {
    super.initState();
    _authSubscription =
        Supabase.instance.client.auth.onAuthStateChange.listen((event) {
      if (event.event == AuthChangeEvent.passwordRecovery && mounted) {
        setState(() {
          _emailSent = true;
          _recoveryReady = true;
        });
      }
    });
  }

  @override
  void dispose() {
    _authSubscription.cancel();
    _emailController.dispose();
    _newPassController.dispose();
    _confirmPassController.dispose();
    super.dispose();
  }

  Future<void> _checkRecoverySession() async {
    final session = Supabase.instance.client.auth.currentSession;
    if (session != null) {
      setState(() => _recoveryReady = true);
      return;
    }

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Open the reset link from your email first.'),
          backgroundColor: Colors.orange,
        ),
      );
    }
  }

  void _handleNext() async {
    final notifier = ref.read(authStateProvider.notifier);
    if (!_emailSent) {
      setState(() => _eEmail = AppValidators.validateEmail(_emailController.text));
      if (_eEmail == null && await notifier.resetPassword(_emailController.text.trim())) {
        setState(() => _emailSent = true);
      }
      return;
    }

    if (!_recoveryReady) {
      _checkRecoverySession();
      return;
    }

    setState(() {
      _eNew = AppValidators.validatePassword(_newPassController.text);
      _eConfirm = _newPassController.text != _confirmPassController.text ? 'Mismatch' : null;
    });
    if (_eNew == null && _eConfirm == null) {
      if (await notifier.confirmNewPassword(
        _emailController.text,
        '',
        _newPassController.text,
        _confirmPassController.text,
      )) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Password updated. Please sign in.')),
          );
          context.goNamed('login');
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authStateProvider);
    final errorMessage = authState.whenOrNull(error: (e, _) => e.toString());

    return Scaffold(
      backgroundColor: AppColors.neutralBackground,
      appBar: AppBar(backgroundColor: Colors.transparent, elevation: 0, leading: IconButton(icon: const Icon(Icons.arrow_back, color: AppColors.primaryBlue), onPressed: () => context.pop())),
      body: Stack(
        fit: StackFit.expand,
        children: [
          Positioned(top: 150, right: -80, child: Opacity(opacity: 0.1, child: Image.asset('assets/images/lungs_watermark.png', width: 450))),
          SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                children: [
                  Image.asset('assets/images/logo_icon.png', height: 72),
                  const SizedBox(height: 12),
                  Text('MediScanX', style: AppTypography.headlineM.copyWith(color: AppColors.primaryBlue)),
                  const SizedBox(height: 32),
                  _buildStepIndicator(),
                  const SizedBox(height: 32),
                  if (errorMessage != null) Text(errorMessage, style: const TextStyle(color: Colors.red)),
                  if (_recoveryReady) ...[
                    const SizedBox(height: 8),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.green.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.green.withOpacity(0.3)),
                      ),
                      child: const Row(
                        children: [
                          Icon(Icons.check_circle_outline, color: Colors.green),
                          SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'Recovery session detected. You can now set a new password.',
                              style: TextStyle(color: Colors.green),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],

                  if (!_emailSent) ...[
                    const Icon(Icons.lock_reset, color: AppColors.primaryBlue, size: 80),
                    const SizedBox(height: 24),
                    Text('Reset Password', style: AppTypography.headlineS),
                    const SizedBox(height: 32),
                    CustomInputField(label: 'Email Address', hint: 'Enter registered email', controller: _emailController, errorText: _eEmail),
                  ] else if (!_recoveryReady) ...[
                    const Icon(Icons.verified, color: AppColors.accentCyan, size: 80),
                    const SizedBox(height: 24),
                    Text('Check Your Email', style: AppTypography.headlineS),
                    const SizedBox(height: 12),
                    Text(
                      'We sent a password reset link to ${_emailController.text.trim()}. Open the link, then return here.',
                      textAlign: TextAlign.center,
                      style: AppTypography.bodyS.copyWith(color: AppColors.textLight),
                    ),
                    const SizedBox(height: 32),
                    OutlinedButton.icon(
                      onPressed: _checkRecoverySession,
                      icon: const Icon(Icons.mark_email_read_outlined),
                      label: const Text('I opened the email link'),
                    ),
                  ] else ...[
                    const Icon(Icons.lock_outline, color: AppColors.riskNormal, size: 80),
                    const SizedBox(height: 24),
                    Text('New Password', style: AppTypography.headlineS),
                    const SizedBox(height: 32),
                    CustomInputField(label: 'New Password', hint: '******', controller: _newPassController, obscureText: _obs1, errorText: _eNew, suffixIcon: IconButton(icon: Icon(_obs1 ? Icons.visibility_off : Icons.visibility), onPressed: () => setState(() => _obs1 = !_obs1))),
                    const SizedBox(height: 16),
                    CustomInputField(label: 'Confirm Password', hint: '******', controller: _confirmPassController, obscureText: _obs2, errorText: _eConfirm, suffixIcon: IconButton(icon: Icon(_obs2 ? Icons.visibility_off : Icons.visibility), onPressed: () => setState(() => _obs2 = !_obs2))),
                  ],
                  const SizedBox(height: 32),
                  CustomButton(label: _emailSent ? (_recoveryReady ? 'UPDATE PASSWORD' : 'CONTINUE') : 'SEND RESET LINK', isLoading: authState.isLoading, onPressed: _handleNext),
                  if (!_emailSent) ...[
                    const SizedBox(height: 24),
                    Container(padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: AppColors.accentCyan.withOpacity(0.1), borderRadius: BorderRadius.circular(8)), child: const Text('In a clinical environment, resets are managed by IT department.', style: TextStyle(color: AppColors.accentCyan))),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStepIndicator() {
    final step = !_emailSent ? 0 : (!_recoveryReady ? 1 : 2);
    return Row(mainAxisAlignment: MainAxisAlignment.center, children: List.generate(3, (i) => Container(margin: const EdgeInsets.symmetric(horizontal: 4), width: 60, height: 4, decoration: BoxDecoration(color: step >= i ? AppColors.accentCyan : AppColors.borderColor, borderRadius: BorderRadius.circular(2)))));
  }
}