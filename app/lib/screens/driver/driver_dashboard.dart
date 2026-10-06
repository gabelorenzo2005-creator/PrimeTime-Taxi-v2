import 'package:flutter/material.dart';

import '../../models/app_user.dart';
import '../operations_dashboard.dart';

class DriverDashboard extends StatelessWidget {
  const DriverDashboard({required this.user, super.key});
  final AppUser user;
  @override
  Widget build(BuildContext context) => OperationsDashboard(user: user);
}
