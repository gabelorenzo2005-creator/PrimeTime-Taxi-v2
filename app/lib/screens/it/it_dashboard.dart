import 'package:flutter/material.dart';

import '../../models/app_user.dart';

import '../auth/login_screen.dart';

class ItDashboard extends StatefulWidget {
  const ItDashboard({
    required this.user,
    super.key,
  });

  final AppUser user;

  @override
  State<ItDashboard> createState() => _ItDashboardState();
}

class _ItDashboardState extends State<ItDashboard> {
  int _selectedTab = 0;

  void _signOut() {
  Navigator.of(context).pushAndRemoveUntil(
    MaterialPageRoute(
      builder: (context) => const LoginScreen(),
    ),
    (route) => false,
  );
}

  void _showUnavailable(String feature) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('$feature is being migrated to the new server.'),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('IT Support Dashboard'),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Center(
              child: Text(widget.user.fullName),
            ),
          ),
          IconButton(
            tooltip: 'Sign Out',
            onPressed: _signOut,
            icon: const Icon(Icons.logout),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: IndexedStack(
        index: _selectedTab,
        children: [
          _overview(),
          _liveMapPlaceholder(),
          _tools(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedTab,
        onDestinationSelected: (value) {
          setState(() {
            _selectedTab = value;
          });
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.monitor_heart_outlined),
            selectedIcon: Icon(Icons.monitor_heart),
            label: 'System',
          ),
          NavigationDestination(
            icon: Icon(Icons.map_outlined),
            selectedIcon: Icon(Icons.map),
            label: 'Live Map',
          ),
          NavigationDestination(
            icon: Icon(Icons.build_outlined),
            selectedIcon: Icon(Icons.build),
            label: 'Tools',
          ),
        ],
      ),
    );
  }

  Widget _overview() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1150),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(22),
                  child: Row(
                    children: [
                      const CircleAvatar(
                        radius: 32,
                        child: Icon(Icons.computer, size: 34),
                      ),
                      const SizedBox(width: 18),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Welcome, ${widget.user.fullName}',
                              style: Theme.of(context).textTheme.headlineSmall,
                            ),
                            const SizedBox(height: 6),
                            const Text(
                              'Monitor GPS health, accounts, and technical status.',
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 20),
              const Text(
                'System diagnostics will appear here as services are connected to the new server.',
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _liveMapPlaceholder() {
    return const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.map_outlined, size: 72),
          SizedBox(height: 16),
          Text('Live Driver Map'),
          SizedBox(height: 8),
          Text('GPS service migration is next.'),
        ],
      ),
    );
  }

  Widget _tools() {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text(
          'IT Tools',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 16,
          runSpacing: 16,
          children: [
            _toolCard(
              title: 'Driver Accounts',
              subtitle: 'Reactivate accounts and correct assignments.',
              icon: Icons.manage_accounts_outlined,
              onTap: () => _showUnavailable('Driver Accounts'),
            ),
            _toolCard(
              title: 'GPS Diagnostics',
              subtitle: 'Review driver tracking and location errors.',
              icon: Icons.gps_fixed,
              onTap: () {
                setState(() {
                  _selectedTab = 0;
                });
              },
            ),
            _toolCard(
              title: 'Vehicle Assignments',
              subtitle: 'Review which driver used each vehicle.',
              icon: Icons.directions_car_outlined,
              onTap: () => _showUnavailable('Vehicle Assignments'),
            ),
            _toolCard(
              title: 'Shift History',
              subtitle: 'Review driver sessions and vehicle usage.',
              icon: Icons.schedule_outlined,
              onTap: () => _showUnavailable('Shift History'),
            ),
            _toolCard(
              title: 'Turn-In Approvals',
              subtitle: 'Clear or reject driver turn-in submissions.',
              icon: Icons.payments_outlined,
              onTap: () => _showUnavailable('Turn-In Approvals'),
            ),
            _toolCard(
              title: 'Safety Alerts',
              subtitle: 'Review and resolve driver emergency alerts.',
              icon: Icons.warning_amber_outlined,
              onTap: () => _showUnavailable('Safety Alerts'),
            ),
            _toolCard(
              title: 'Application Logs',
              subtitle: 'Review errors and technical events.',
              icon: Icons.article_outlined,
              onTap: () => _showUnavailable('Application Logs'),
            ),
            _toolCard(
              title: 'System Health',
              subtitle: 'Review server and application connection status.',
              icon: Icons.monitor_heart_outlined,
              onTap: () {
                setState(() {
                  _selectedTab = 0;
                });
              },
            ),
          ],
        ),
      ],
    );
  }

  Widget _toolCard({
    required String title,
    required String subtitle,
    required IconData icon,
    required VoidCallback onTap,
  }) {
    return SizedBox(
      width: 320,
      child: Card(
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Row(
              children: [
                CircleAvatar(
                  child: Icon(icon),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 4),
                      Text(subtitle),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}