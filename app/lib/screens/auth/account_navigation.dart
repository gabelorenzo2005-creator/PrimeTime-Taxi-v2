import 'package:flutter/material.dart';

import '../../models/app_user.dart';
import '../../services/auth_service.dart';
import '../admin/admin_dashboard.dart';
import '../dispatcher/dispatcher_dashboard.dart';
import '../driver/driver_dashboard.dart';
import '../it/it_dashboard.dart';
import 'password_screen.dart';

Future<bool> openAccount(BuildContext context, AppUser account) async {
  var user = account;
  if (user.mustChangePassword) {
    final changed = await Navigator.of(
      context,
    ).push<AppUser>(MaterialPageRoute(builder: (_) => const PasswordScreen()));
    if (!context.mounted) return false;
    if (changed == null) {
      await AuthService().signOut();
      return false;
    }
    user = changed;
  }
  if (!context.mounted) return false;
  final Widget page = switch (user.role) {
    'DRIVER' => DriverDashboard(user: user),
    'DISPATCHER' => DispatcherDashboard(user: user),
    'ADMIN' => AdminDashboard(user: user),
    'IT' => ItDashboard(user: user),
    _ => throw StateError('Unsupported account role'),
  };
  Navigator.of(context)
      .pushReplacement(MaterialPageRoute(builder: (_) => page));
  return true;
}
