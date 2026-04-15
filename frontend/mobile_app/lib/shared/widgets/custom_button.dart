import 'package:flutter/material.dart';

import '../../core/themes/app_colors.dart';
import '../../core/themes/app_typography.dart';

class CustomButton extends StatelessWidget{
  final String label;
  final VoidCallback onPressed;
  final bool isLoading;
  final bool enabled;
  final bool showArrow;
  final Color? backgroundColor;
  final Color? textColor;

  const CustomButton({
    Key? key,
    required this.label,
    required this.onPressed,
    this.isLoading = false,
    this.enabled = true,
    this.showArrow = true,
    this.backgroundColor,
    this.textColor,
}) : super(key: key);

  @override
  Widget build(BuildContext context){
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton(
        onPressed: enabled && !isLoading ? onPressed : null,
        style: ElevatedButton.styleFrom(
          backgroundColor: backgroundColor ?? AppColors.primaryBlue,
          disabledBackgroundColor: AppColors.borderColor,
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
        ),
        elevation: 0,
      ),
      child: isLoading
      ? SizedBox(
        height: 20,
        width: 20,
        child: CircularProgressIndicator(
          strokeWidth: 2,
          valueColor: AlwaysStoppedAnimation<Color>(textColor ?? AppColors.white),
    ),
    )
          : Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                label,
                style: AppTypography.labelM.copyWith(
                  color: textColor ?? AppColors.white,
                  fontWeight: FontWeight.w600,
                ),
              ),
              if (showArrow) ...[
                const SizedBox(width: 8),
                Icon(
                  Icons.arrow_forward,
                  color: textColor ?? AppColors.white,
                  size: 18,
                ),
              ],
            ],
          ),
    ),
    );
  }
}