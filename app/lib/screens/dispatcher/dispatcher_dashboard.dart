import 'package:flutter/material.dart';

import '../../models/app_user.dart';
import '../operations_dashboard.dart';

class DispatcherDashboard extends StatelessWidget {
  const DispatcherDashboard({required this.user, super.key});
  final AppUser user;
  @override
  Widget build(BuildContext context) => OperationsDashboard(user: user);
}
