
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import '../../core/themes/app_colors.dart';
import '../../core/themes/app_typography.dart';

class UserTypeToggle extends StatelessWidget {
  final String selectedType;
  final ValueChanged<String> onChanged;

  const UserTypeToggle({
    Key? key,
    required this.selectedType,
    required this.onChanged,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(6), // Slightly more padding for a cleaner look
      decoration: BoxDecoration(
        color: AppColors.borderColor.withValues(alpha: 0.2), // Light background for the track
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          // 1. PATIENT BUTTON
          Expanded(
            child: _ToggleButton(
              label: 'Patient',
              icon: Icons.person_outline,
              isSelected: selectedType == 'patient',
              onPressed: () => onChanged('patient'),
            ),
          ),
          const SizedBox(width: 8), // Gap between buttons
          // 2. DOCTOR BUTTON (Was missing!)
          Expanded(
            child: _ToggleButton(
              label: 'Doctor',
              icon: Icons.medical_services_outlined,
              isSelected: selectedType == 'doctor',
              onPressed: () => onChanged('doctor'),
            ),
          ),
        ],
      ),
    );
  }
}

class _ToggleButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool isSelected;
  final VoidCallback onPressed;

  const _ToggleButton({
    required this.label,
    required this.icon,
    required this.isSelected,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onPressed,
      child: AnimatedContainer( // Added animation for a smoother FYP feel
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          color: isSelected ? AppColors.primaryBlue : Colors.transparent,
          borderRadius: BorderRadius.circular(10),
          boxShadow: isSelected
              ? [BoxShadow(color: AppColors.primaryBlue.withValues(alpha: 0.3), blurRadius: 8, offset: const Offset(0, 4))]
              : [],
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              icon,
              color: isSelected ? AppColors.white : AppColors.textLight,
              size: 18,
            ),
            const SizedBox(width: 8),
            Text(
              label,
              style: AppTypography.labelM.copyWith(
                color: isSelected ? AppColors.white : AppColors.textLight,
                fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
              ),
            ),
          ],
        ),
      ),
    );
  }
}