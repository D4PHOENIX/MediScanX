import 'package:flutter/material.dart';
import 'app_colors.dart';
import 'app_typography.dart';

class AppTheme{
  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.light(
        primary: AppColors.primaryBlue,
        secondary: AppColors.accentCyan,
        background: AppColors.neutralBackground,
        surface: AppColors.white,
        error: AppColors.riskHigh,
        onPrimary: AppColors.white,
        onSecondary: AppColors.white,
        onBackground: AppColors.textDark,
        onSurface: AppColors.textDark,
        onError: AppColors.white,
      ),
      scaffoldBackgroundColor: AppColors.neutralBackground,
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.primaryBlue,
        foregroundColor: AppColors.white,
        elevation: 0,
        centerTitle: true,
      ),
    );
  }
}