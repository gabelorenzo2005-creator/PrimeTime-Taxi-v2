import 'package:flutter/material.dart';

import 'screens/auth/login_screen.dart';

void main() {
  runApp(const PrimeTimeTaxiApp());
}

class PrimeTimeTaxiApp extends StatelessWidget {
  const PrimeTimeTaxiApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Prime Time Taxi',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.blue,
        ),
        useMaterial3: true,
      ),
      home: const LoginScreen(),
    );
  }
}