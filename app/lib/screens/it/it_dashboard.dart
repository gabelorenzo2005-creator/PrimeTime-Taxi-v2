import 'package:flutter/material.dart';

import '../../models/app_user.dart';
import '../role_dashboard.dart';

class ItDashboard extends StatelessWidget {
  const ItDashboard({
    required this.user,
    super.key,
  });

  final AppUser user;

  @override
  Widget build(BuildContext context) {
    return RoleDashboard(
      user: user,
      title: 'Technician Dashboard',
      icon: Icons.build_outlined,
      description:
          'Manage Prime Time Taxi system operations, accounts, and technical tools.',
    );
  }
}
