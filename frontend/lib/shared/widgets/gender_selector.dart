import 'package:flutter/material.dart';
import 'package:mediscanx_mobile/core/themes/app_colors.dart';

import '../../core/themes/app_typography.dart';

class GenderSelector extends StatelessWidget{
  final String? selectedGender;
  final ValueChanged<String?> onChanged;

  const GenderSelector({
    Key? key,
    this.selectedGender,
    required this.onChanged,
  }) : super(key: key);

  @override
  Widget build(BuildContext context){
    final genders = ['Male', 'Female', 'Other'];

    return Row(
      children: List.generate(
        genders.length * 2 -1,
          (index) {
         if (index.isEven) {
           final genderIndex = index ~/ 2;
           final gender = genders[genderIndex];
           final isSelected = selectedGender == gender;

           return Expanded(
             child: GestureDetector(
               onTap: () => onChanged(gender),
               child: Container(
                 padding: const EdgeInsets.symmetric(vertical: 10),
                 decoration: BoxDecoration(
                   color: isSelected
                      ? AppColors.primaryBlue
                      : AppColors.white,
                   border: Border.all(
                     color: isSelected
                         ? AppColors.primaryBlue
                         : AppColors.borderColor,
                   ),
                   borderRadius: BorderRadius.circular(10),
                 ),
                 child: Center(
                   child: Text(
                     gender,
                     style: AppTypography.bodyS.copyWith(
                       color: isSelected
                           ? AppColors.white
                           : AppColors.textLight,
                      ),
                    ),
                  ),
                ),
              ),
           );
         } else {
           return const SizedBox(width: 8);
         }
        },
      ),
    );
  }
}