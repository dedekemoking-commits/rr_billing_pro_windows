import 'package:flutter/material.dart';

class AppTheme {
  static const Color primaryColor = Color(0xFF00E676);
  static const Color primaryDark = Color(0xFF00C853);
  static const Color bgColor = Color(0xFF0D1117);
  static const Color cardColor = Color(0xFF161B22);
  static const Color surfaceColor = Color(0xFF21262D);
  static const Color textPrimary = Color(0xFFF0F6FC);
  static const Color textSecondary = Color(0xFF8B949E);
  static const Color accentBlue = Color(0xFF58A6FF);
  static const Color accentOrange = Color(0xFFF78166);
  static const Color errorColor = Color(0xFFF85149);
  static const Color successColor = Color(0xFF3FB950);

  static ThemeData get darkTheme => ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: bgColor,
        primaryColor: primaryColor,
        colorScheme: const ColorScheme.dark(
          primary: primaryColor,
          secondary: primaryDark,
          surface: cardColor,
          error: errorColor,
        ),
        cardTheme: CardTheme(
          color: cardColor,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: const BorderSide(color: surfaceColor, width: 1),
          ),
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: bgColor,
          elevation: 0,
          centerTitle: true,
          titleTextStyle: TextStyle(
            color: textPrimary,
            fontSize: 18,
            fontWeight: FontWeight.w600,
          ),
          iconTheme: IconThemeData(color: textPrimary),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: surfaceColor,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: BorderSide.none,
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: BorderSide.none,
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: primaryColor, width: 1.5),
          ),
          hintStyle: const TextStyle(color: textSecondary),
          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: primaryColor,
            foregroundColor: Colors.black,
            minimumSize: const Size(double.infinity, 50),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
            textStyle: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        textTheme: const TextTheme(
          headlineLarge: TextStyle(color: textPrimary, fontWeight: FontWeight.bold),
          headlineMedium: TextStyle(color: textPrimary, fontWeight: FontWeight.w600),
          titleLarge: TextStyle(color: textPrimary, fontWeight: FontWeight.w600),
          titleMedium: TextStyle(color: textPrimary),
          bodyLarge: TextStyle(color: textPrimary),
          bodyMedium: TextStyle(color: textSecondary),
          bodySmall: TextStyle(color: textSecondary),
        ),
      );
}
