import 'dart:async';

import 'package:flutter/material.dart';

import '../models/app_user.dart';
import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/location_service.dart';
import 'auth/login_screen.dart';
import 'auth/password_screen.dart';

typedef Record = Map<String, dynamic>;

/// Shared server-backed workspace; role-specific entry points live in their folders.
class OperationsDashboard extends StatefulWidget {
  const OperationsDashboard({
    required this.user,
    this.locationService,
    super.key,
  });
  final DriverLocationService? locationService;
  final AppUser user;
  @override
  State<OperationsDashboard> createState() => _OperationsDashboardState();
}

class _OperationsDashboardState extends State<OperationsDashboard>
    with WidgetsBindingObserver {
  late final DriverLocationService _location;
  bool _nativeInitialized = false;
  bool _resumeTracking = false;
  int _workspaceRevision = 0;
  Record? _data;
  String? _error;
  bool _loading = false;
  bool _busy = false;
  int _tab = 0;
  String _tripFilter = 'Active';
  Timer? _poller;
  DateTime? _lastRefresh;
  bool _leaving = false;
  String? _viewAsRole;
  bool _previewDenied = false;
  static const _dashboardRoles = {
    'DRIVER': 'Driver',
    'DISPATCHER': 'Dispatcher',
    'ADMIN': 'Admin',
    'IT': 'Technician',
  };
  String get _uiRole => _viewAsRole ?? widget.user.role;
  bool get _developerAccess =>
      !_previewDenied &&
      _data?['user']?['development_dashboard_access'] == true;
  bool get _driver => _uiRole == 'DRIVER';
  bool get _manage => ['ADMIN', 'IT'].contains(_uiRole);
  bool get _dispatch => ['ADMIN', 'DISPATCHER'].contains(_uiRole);
  List<Record> _records(String key) => ((_data?[key] as List?) ?? [])
      .map((e) => Map<String, dynamic>.from(e as Map))
      .toList();
  Record? get _myShift {
    for (final shift in _records('shifts')) {
      if (shift['end_time'] == null && shift['driver'] == _data?['driver_id']) {
        return shift;
      }
    }
    return null;
  }

  List<Record> get _activeTrips =>
      _records('trips')
          .where((t) => ['ASSIGNED', 'IN_PROGRESS'].contains(t['status']))
          .toList();

  @override
  void initState() {
    super.initState();
    _location = widget.locationService ?? NativeDriverLocationService();
    AuthService.tracking = _location;
    WidgetsBinding.instance.addObserver(this);
    _refresh();
    _poller = Timer.periodic(const Duration(seconds: 10), (_) {
      if (!_busy) _refresh();
    });
  }

  @override
  void dispose() {
    _poller?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_location.stop());
    if (identical(AuthService.tracking, _location)) {
      AuthService.tracking = null;
      AuthService.push.suspend();
    }
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _resumeTracking = true;
      _poller ??= Timer.periodic(const Duration(seconds: 10), (_) {
        if (!_busy) _refresh();
      });
      unawaited(_refresh());
      unawaited(AuthService.push.register());
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden) {
      _poller?.cancel();
      _poller = null;
    }
  }

  Future<void> _startTracking() async {
    final shift = _myShift;
    if (widget.user.role == 'DRIVER' && _driver && shift != null) {
      await _location.start(
        shift['id'] as int,
        DateTime.parse(shift['start_time'] as String),
      );
    }
  }

  void _login({bool cleanup = true}) {
    if (!mounted || _leaving) return;
    _leaving = true;
    unawaited(_location.stop());
    AuthService.push.suspend();
    if (cleanup) unawaited(AuthService().signOut());
    _data = null;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  Future<void> _refresh() async {
    if (_loading || _leaving) return;
    setState(() => _loading = true);
    final revision = _workspaceRevision;
    var restoreNormalWorkspace = false;
    try {
      final result = await ApiClient.request(
        _viewAsRole == null
            ? 'workspace/'
            : 'development/dashboard/?role=$_viewAsRole',
      );
      if (!mounted || _leaving || revision != _workspaceRevision) return;
      setState(() {
        _data = result;
        _error = null;
        _lastRefresh = DateTime.now();
      });
      if (_driver && _myShift == null) await _location.stop();
      if (!_nativeInitialized || _resumeTracking) {
        _resumeTracking = false;
        _nativeInitialized = true;
        await _startTracking();
        if (mounted && !_leaving) {
          unawaited(AuthService.push.start());
        }
      }
    } catch (error) {
      if (!mounted) return;
      if (error is ApiException && error.status == 401) {
        _login();
        return;
      }
      if (error is ApiException && error.status == 403 && _viewAsRole != null) {
        setState(() {
          _viewAsRole = null;
          _previewDenied = true;
          _data = null;
          _tab = 0;
        });
        restoreNormalWorkspace = true;
      }
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
    if (restoreNormalWorkspace && mounted && !_leaving) await _refresh();
  }

  Future<void> _viewDashboardAs(String role) async {
    if (!_developerAccess || _busy || _loading) return;
    setState(() => _busy = true);
    _workspaceRevision++;
    try {
      final result = await ApiClient.request(
        'development/dashboard/?role=$role',
      );
      if (!mounted || _leaving) return;
      if (result['user']?['development_dashboard_access'] != true ||
          result['view_as_role'] != role) {
        throw const ApiException(
          'Development preview authorization was not confirmed.',
          403,
        );
      }
      setState(() {
        _viewAsRole = role == widget.user.role ? null : role;
        _data = result;
        _tab = 0;
        _tripFilter = 'Active';
        _error = null;
      });
    } catch (error) {
      if (!mounted || _leaving) return;
      if (error is ApiException && error.status == 401) {
        _login();
        return;
      }
      if (error is ApiException && error.status == 403) {
        setState(() {
          _previewDenied = true;
          _viewAsRole = null;
          _data = null;
          _tab = 0;
        });
        await _refresh();
      }
      _notice(error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _perform(
    String path, {
    Record? body,
    String method = 'POST',
    String message = 'Saved',
    Future<void> Function(Record)? onSuccess,
  }) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final result = await ApiClient.request(
        path,
        method: method,
        body: body ?? {},
      );
      if (!mounted || _leaving) return;
      _workspaceRevision++;
      if (onSuccess != null) await onSuccess(result);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
      await _refresh();
    } catch (error) {
      if (!mounted) return;
      if (error is ApiException && error.status == 401) {
        _login();
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(error.toString()),
          duration: const Duration(seconds: 8),
        ),
      );
      await _refresh();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<Record?> _form(String title, List<_Field> fields) =>
      showDialog<Record>(
        context: context,
        builder: (_) => _RecordForm(title: title, fields: fields),
      );
  Future<void> _clockIn() async {
    final vehicles = _records('vehicles');
    if (vehicles.isEmpty) {
      _notice('Ask Admin or IT to add a vehicle first.');
      return;
    }
    final data = await _form('Clock In', [
      _Field(
        'vehicle_id',
        'Vehicle',
        choices: {
          for (final v in vehicles)
            '${v['id']}':
                'Car ${v['car_number']} • ${v['license_plate_number']}',
        },
      ),
    ]);
    if (data != null) {
      await _perform(
        'shifts/',
        body: {'vehicle_id': int.parse(data['vehicle_id'])},
        message: 'Shift started',
        onSuccess: (shift) async {
          if (widget.user.role == 'DRIVER' &&
              _driver &&
              shift['id'] != null &&
              shift['start_time'] != null) {
            await _location.start(
              shift['id'] as int,
              DateTime.parse(shift['start_time'] as String),
            );
          }
        },
      );
    }
  }

  Future<void> _clockOut(Record shift) async {
    final data = await _form('Clock Out • Shift ${shift['shift_number']}', [
      const _Field('amount', 'Turn-in amount', money: true),
    ]);
    if (data != null) {
      await _perform(
        'shifts/${shift['id']}/end/',
        body: data,
        message: 'Shift ended; turn-in submitted',
        onSuccess: (_) => _location.stop(),
      );
    }
  }

  Future<void> _createTrip() async {
    final data = await showDialog<Record>(
      context: context,
      builder: (_) => const _TripForm(),
    );
    if (data != null) {
      await _perform('trips/', body: data, message: 'Call created');
    }
  }

  Future<void> _assign(Record trip) async {
    final drivers = _records('drivers');
    final shifts = _records('shifts')
        .where((s) => s['end_time'] == null)
        .toList();
    final busyDrivers = _activeTrips.map((t) => t['driver']).toSet();
    final choices = <String, String>{
      for (final d in drivers)
        if (shifts.any((s) => s['driver'] == d['id']) &&
            !busyDrivers.contains(d['id']))
          '${d['id']}': '${d['call_number']} • ${d['name']}',
    };
    if (choices.isEmpty) {
      _notice('No available driver is clocked in.');
      return;
    }
    final data = await _form('Assign Call #${trip['id']}', [
      _Field('driver_id', 'Driver', choices: choices),
    ]);
    if (data != null) {
      await _perform(
        'trips/${trip['id']}/assign/',
        body: {'driver_id': int.parse(data['driver_id'])},
        message: 'Driver assigned',
      );
    }
  }

  Future<void> _complete(Record trip) async {
    final data = await _form('Complete Call #${trip['id']}', [
      const _Field('amount', 'Final fare', money: true),
    ]);
    if (data != null) {
      await _perform(
        'trips/${trip['id']}/complete/',
        body: data,
        message: 'Trip completed',
      );
    }
  }

  Future<void> _cancel(Record trip) async {
    final data = await _form('Cancel Call #${trip['id']}', [
      const _Field('reason', 'Cancellation reason'),
    ]);
    if (data != null) {
      await _perform(
        'trips/${trip['id']}/cancel/',
        body: data,
        message: 'Call cancelled',
      );
    }
  }

  Future<void> _alert() async {
    final data = await _form('Send Safety Alert', [
      const _Field(
        'kind',
        'Reason',
        choices: {
          'PANIC': 'Panic',
          'PULLED_OVER': 'Pulled over',
          'ACCIDENT': 'Accident',
          'BREAKDOWN': 'Breakdown',
          'OTHER': 'Other',
        },
      ),
      const _Field('notes', 'Details', required: false),
    ]);
    if (data != null) {
      await _perform(
        'alerts/',
        body: data,
        message: 'Alert saved for dispatch',
      );
    }
  }

  void _notice(String message) {
    if (mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<void> _signOut() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      _leaving = true;
      _poller?.cancel();
      await AuthService().signOut();
      _leaving = false;
      _login(cleanup: false);
    } catch (error) {
      if (error is ApiException && error.status == 401) {
        _login();
        return;
      }
      _leaving = false;
      _login();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final destinations = [
      const NavigationDestination(
        icon: Icon(Icons.dashboard_outlined),
        label: 'Overview',
      ),
      const NavigationDestination(
        icon: Icon(Icons.local_taxi_outlined),
        label: 'Trips',
      ),
      const NavigationDestination(icon: Icon(Icons.schedule), label: 'Shifts'),
      if (_manage)
        const NavigationDestination(
          icon: Icon(Icons.people_outline),
          label: 'Management',
        ),
      const NavigationDestination(
        icon: Icon(Icons.warning_amber),
        label: 'Safety',
      ),
    ];
    final pages = [
      _overview(),
      _trips(),
      _shifts(),
      if (_manage) _management(),
      _alerts(),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Text(
          'PrimeTime • ${_dashboardRoles[_uiRole] ?? widget.user.roleDisplay}',
        ),
        actions: [
          if (_driver && _data?['turn_in_lock']?['blocked'] == true)
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text(
                'Your required turn-in needs Admin or IT clearance before another shift or trip. You can still view your history.',
              ),
            ),
          if (_driver)
            IconButton(
              tooltip: 'Send safety alert',
              onPressed: _busy ? null : _alert,
              icon: const Icon(Icons.warning_amber, color: Colors.red),
            ),
          IconButton(
            tooltip: 'Refresh',
            onPressed: _loading ? null : _refresh,
            icon: const Icon(Icons.refresh),
          ),
          IconButton(
            tooltip: 'Change password',
            onPressed: _busy
                ? null
                : () async {
                    await Navigator.push(
                      context,
                      MaterialPageRoute(builder: (_) => const PasswordScreen()),
                    );
                    if (mounted) _refresh();
                  },
            icon: const Icon(Icons.lock_outline),
          ),
          IconButton(
            tooltip: 'Sign out',
            onPressed: _busy ? null : _signOut,
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: Column(
        children: [
          if (_developerAccess)
            Material(
              color: Theme.of(context).colorScheme.tertiaryContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'DEVELOPMENT ACCESS • Authenticated as ${widget.user.roleDisplay}',
                    ),
                    Text(
                      'Viewing ${_dashboardRoles[_uiRole]} dashboard • API permissions remain ${widget.user.roleDisplay}',
                    ),
                    Wrap(
                      spacing: 16,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        const Text('View Dashboard As'),
                        DropdownButton<String>(
                          key: const ValueKey('view-dashboard-as'),
                          value: _uiRole,
                          items: [
                            for (final entry in _dashboardRoles.entries)
                              DropdownMenuItem(
                                value: entry.key,
                                child: Text(entry.value),
                              ),
                          ],
                          onChanged: _busy || _loading
                              ? null
                              : (role) {
                                  if (role != null) _viewDashboardAs(role);
                                },
                        ),
                        if (_viewAsRole != null)
                          OutlinedButton(
                            onPressed: _busy || _loading
                                ? null
                                : () => _viewDashboardAs('IT'),
                            child: const Text('Return to Technician'),
                          ),
                      ],
                    ),
                    if (_driver && widget.user.role != 'DRIVER')
                      const Text(
                        'Driver layout preview only. GPS is off; Driver-only API actions remain protected.',
                      ),
                  ],
                ),
              ),
            ),
          if (_driver)
            ValueListenableBuilder<String>(
              valueListenable: _location.status,
              builder: (context, status, _) => Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 4,
                ),
                child: Row(
                  children: [
                    Expanded(child: Text(status)),
                    if (_myShift != null)
                      TextButton(
                        onPressed: _busy ? null : _startTracking,
                        child: const Text('Retry GPS'),
                      ),
                  ],
                ),
              ),
            ),
          if (_loading || _busy) const LinearProgressIndicator(),
          if (_error != null)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              color: Theme.of(context).colorScheme.errorContainer,
              child: Text(_error!),
            ),
          Expanded(
            child: _data == null
                ? Center(
                    child: _loading
                        ? const CircularProgressIndicator()
                        : FilledButton(
                            onPressed: _refresh,
                            child: const Text('Retry Connection'),
                          ),
                  )
                : AbsorbPointer(absorbing: _busy, child: pages[_tab]),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (index) => setState(() => _tab = index),
        destinations: destinations,
      ),
    );
  }

  Widget _page(List<Widget> children) => RefreshIndicator(
    onRefresh: _refresh,
    child: ListView(
      padding: const EdgeInsets.all(20),
      physics: const AlwaysScrollableScrollPhysics(),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1200),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: children,
            ),
          ),
        ),
      ],
    ),
  );
  Widget _heading(String title, [String? subtitle]) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.headlineSmall),
        if (subtitle != null) Text(subtitle),
      ],
    ),
  );
  Widget _empty(String text) => Card(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Text(text, textAlign: TextAlign.center),
    ),
  );
  String _date(dynamic value) {
    final date = DateTime.tryParse(value?.toString() ?? '')?.toLocal();
    if (date == null) return '—';
    return '${date.month}/${date.day}/${date.year} ${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';
  }

  String _status(dynamic value) => value.toString().replaceAll('_', ' ');
  Widget _overview() {
    final shift = _myShift;
    final openCount = _records('trips')
        .where((t) => t['status'] == 'OPEN')
        .length;
    final activeShifts = _records('shifts')
        .where((s) => s['end_time'] == null)
        .toList();
    final pendingAlerts = _records('alerts')
        .where((a) => a['resolved_at'] == null)
        .length;
    return _page([
      _heading(
        'Welcome, ${widget.user.fullName}',
        '${widget.user.username} • ${widget.user.roleDisplay}',
      ),
      Wrap(
        spacing: 12,
        runSpacing: 12,
        children: [
          _metric('Open calls', openCount, Icons.list_alt),
          _metric('Active trips', _activeTrips.length, Icons.local_taxi),
          _metric(
            _driver ? 'Active shift' : 'Active shifts',
            activeShifts.length,
            Icons.schedule,
          ),
          _metric('Unresolved alerts', pendingAlerts, Icons.warning_amber),
        ],
      ),
      const SizedBox(height: 20),
      if (_driver)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  shift == null
                      ? 'Off shift'
                      : 'Shift ${shift['shift_number']} • Car ${shift['car_number']}',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: shift == null ? _clockIn : () => _clockOut(shift),
                  icon: Icon(shift == null ? Icons.login : Icons.logout),
                  label: Text(shift == null ? 'Clock In' : 'Clock Out'),
                ),
              ],
            ),
          ),
        ),
      if (_dispatch)
        Wrap(
          spacing: 12,
          children: [
            FilledButton.icon(
              onPressed: _createTrip,
              icon: const Icon(Icons.add),
              label: const Text('Create Call / Reservation'),
            ),
          ],
        ),
      const SizedBox(height: 20),
      if (!_driver) ...[
        _heading('On-shift drivers'),
        if (activeShifts.isEmpty) _empty('No drivers are clocked in.'),
        for (final s in activeShifts)
          Card(
            child: ListTile(
              leading: const Icon(Icons.local_taxi),
              title: Text('${s['call_number']} • ${s['driver_name']}'),
              subtitle: Text(
                'Car ${s['car_number']} • Shift ${s['shift_number']}',
              ),
              trailing: Chip(
                label: Text(
                  _activeTrips.any((t) => t['driver'] == s['driver'])
                      ? 'On trip'
                      : 'Available',
                ),
              ),
            ),
          ),
      ],
      const SizedBox(height: 12),
      Text(
        'Updated ${_date(_lastRefresh?.toIso8601String())} • Refreshes every 10 seconds',
        style: Theme.of(context).textTheme.bodySmall,
      ),
    ]);
  }

  Widget _metric(String label, int count, IconData icon) => SizedBox(
    width: 220,
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            Icon(icon),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '$count',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  Text(label),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );
  Widget _trips() {
    final now = DateTime.now();
    final trips = _records('trips').where((t) {
      final future = (DateTime.tryParse(t['pickup_time']) ?? now).isAfter(now);
      if (_tripFilter == 'History') {
        return ['COMPLETED', 'CANCELLED'].contains(t['status']);
      }
      if (_tripFilter == 'Reservations') {
        return future && !['COMPLETED', 'CANCELLED'].contains(t['status']);
      }
      return !['COMPLETED', 'CANCELLED'].contains(t['status']);
    }).toList();
    return _page([
      _heading('Trip Board', 'History shows the latest 100 records.'),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final filter in [
            'Active',
            if (!_driver) 'Reservations',
            'History',
          ])
            ChoiceChip(
              label: Text(filter),
              selected: _tripFilter == filter,
              onSelected: (_) => setState(() => _tripFilter = filter),
            ),
          if (_dispatch)
            FilledButton.icon(
              onPressed: _createTrip,
              icon: const Icon(Icons.add),
              label: const Text('Create Call'),
            ),
        ],
      ),
      const SizedBox(height: 16),
      if (trips.isEmpty) _empty('No calls in this view.'),
      for (final trip in trips) _tripCard(trip),
    ]);
  }

  Widget _tripCard(Record t) {
    final status = t['status'];
    final terminal = ['COMPLETED', 'CANCELLED'].contains(status);
    final own = t['driver'] == _data?['driver_id'];
    final operate = _dispatch || (_driver && own);
    final due = !(DateTime.tryParse(t['pickup_time']) ?? DateTime.now())
        .isAfter(DateTime.now());
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 12,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  'Call #${t['id']}',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                Chip(label: Text(_status(status))),
              ],
            ),
            Text('Pickup: ${t['pick_up_location']}'),
            Text('Drop-off: ${t['drop_off_location']}'),
            Text('Scheduled: ${_date(t['pickup_time'])}'),
            if (t['driver_name'] != null)
              Text(
                'Driver: ${t['call_number']} • ${t['driver_name']} • Car ${t['car_number']}',
              ),
            if (t['trip_notes'] != null &&
                t['trip_notes'].toString().isNotEmpty)
              Text('Notes: ${t['trip_notes']}'),
            if (t['fare_amount'] != null) Text('Fare: \$${t['fare_amount']}'),
            if (t['cancellation_reason'].toString().isNotEmpty)
              Text('Cancellation: ${t['cancellation_reason']}'),
            const SizedBox(height: 12),
            Wrap(
              spacing: 10,
              runSpacing: 8,
              children: [
                if (status == 'OPEN' &&
                    _driver &&
                    _myShift != null &&
                    _activeTrips.isEmpty &&
                    due)
                  FilledButton(
                    onPressed: () => _perform(
                      'trips/${t['id']}/accept/',
                      message: 'Call accepted',
                    ),
                    child: const Text('Accept Call'),
                  ),
                if (status == 'OPEN' && _dispatch)
                  FilledButton(
                    onPressed: () => _assign(t),
                    child: const Text('Assign Driver'),
                  ),
                if (status == 'ASSIGNED' && operate)
                  FilledButton(
                    onPressed: () => _perform(
                      'trips/${t['id']}/pickup/',
                      message: 'Pickup recorded',
                    ),
                    child: const Text('Passenger Picked Up'),
                  ),
                if (status == 'IN_PROGRESS' && operate)
                  FilledButton(
                    onPressed: () => _complete(t),
                    child: const Text('Complete Trip'),
                  ),
                if (!terminal && operate)
                  OutlinedButton(
                    onPressed: () => _cancel(t),
                    child: const Text('Cancel Call'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _shifts() {
    final shifts = _records('shifts');
    return _page([
      _heading(
        'Shifts & Turn-Ins',
        'Historical shifts show the latest 100 records. Amounts are entered manually.',
      ),
      if (_driver)
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Align(
            alignment: Alignment.centerLeft,
            child: FilledButton(
              onPressed: _myShift == null
                  ? _clockIn
                  : () => _clockOut(_myShift!),
              child: Text(_myShift == null ? 'Clock In' : 'Clock Out'),
            ),
          ),
        ),
      if (shifts.isEmpty) _empty('No shifts yet.'),
      for (final s in shifts)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Shift ${s['shift_number']} • ${s['driver_name']}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Text(
                  'Car ${s['car_number']} • Started ${_date(s['start_time'])}',
                ),
                Text(
                  s['end_time'] == null
                      ? 'Active'
                      : 'Ended ${_date(s['end_time'])}',
                ),
                if (s['end_time'] != null) ...[
                  Text(
                    'Turn-in: \$${s['turn_in_amount'] ?? '—'} • ${s['turn_in_cleared'] == true ? 'Cleared' : 'Pending / uncleared'}',
                  ),
                  if (_manage)
                    Wrap(
                      spacing: 12,
                      children: [
                        if (s['turn_in_cleared'] != true)
                          FilledButton(
                            onPressed: () => _perform(
                              'shifts/${s['id']}/approve/',
                              message: 'Turn-in marked paid and cleared',
                            ),
                            child: const Text('Mark Paid & Clear'),
                          ),
                        if (s['turn_in_cleared'] == true)
                          OutlinedButton(
                            onPressed: () => _perform(
                              'shifts/${s['id']}/reject/',
                              message: 'Turn-in marked uncleared',
                            ),
                            child: const Text('Mark Uncleared'),
                          ),
                      ],
                    ),
                ],
              ],
            ),
          ),
        ),
    ]);
  }

  Future<void> _editRecord(String resource, Record? record) async {
    final fields = switch (resource) {
      'owners' => [const _Field('name', 'Owner name')],
      'vehicles' => [
        const _Field('car_number', 'Car number (up to 3 characters)'),
        const _Field(
          'license_plate_number',
          'License plate (up to 7 characters)',
        ),
        _Field(
          'owner',
          'Owner',
          choices: {
            for (final o in _records('owners')) '${o['id']}': o['name'],
          },
        ),
      ],
      _ => [
        const _Field('first_name', 'First name'),
        const _Field('last_name', 'Last name'),
        const _Field('call_number', 'Call number'),
        const _Field('hack_license_number', 'Hack license number'),
        const _Field('phone_number', 'Phone'),
        const _Field('email', 'Email'),
        const _Field('notes', 'Notes', required: false),
      ],
    };
    if (resource == 'vehicles' && _records('owners').isEmpty) {
      _notice('Add a vehicle owner first.');
      return;
    }
    final data = await _form(
      '${record == null ? 'Add' : 'Edit'} ${resource.substring(0, resource.length - 1)}',
      fields.map((f) => f.withValue(record?[f.key]?.toString())).toList(),
    );
    if (data == null) return;
    if (data.containsKey('owner')) data['owner'] = int.parse(data['owner']);
    await _perform(
      'records/$resource/${record == null ? '' : '${record['id']}/'}',
      body: data,
      method: record == null ? 'POST' : 'PATCH',
    );
  }

  Widget _management() => _page([
    _heading(
      'Company Records',
      'Account roles and driver-account links are managed through Django admin.',
    ),
    for (final resource in ['drivers', 'vehicles', 'owners']) ...[
      Row(
        children: [
          Expanded(
            child: Text(
              resource.toUpperCase(),
              style: Theme.of(context).textTheme.titleLarge,
            ),
          ),
          TextButton.icon(
            onPressed: () => _editRecord(resource, null),
            icon: const Icon(Icons.add),
            label: const Text('Add'),
          ),
        ],
      ),
      if (_records(resource).isEmpty) _empty('No $resource yet.'),
      for (final item in _records(resource))
        Card(
          child: ListTile(
            title: Text(
              resource == 'drivers'
                  ? '${item['call_number']} • ${item['name']}'
                  : resource == 'vehicles'
                  ? 'Car ${item['car_number']} • ${item['license_plate_number']}'
                  : item['name'],
            ),
            subtitle: resource == 'drivers'
                ? Text(
                    item['username'] == null
                        ? 'No linked account'
                        : 'Account: ${item['username']}',
                  )
                : resource == 'vehicles'
                ? Text('Owner: ${item['owner_name']}')
                : null,
            trailing: IconButton(
              tooltip: 'Edit',
              icon: const Icon(Icons.edit_outlined),
              onPressed: () => _editRecord(resource, item),
            ),
          ),
        ),
      const SizedBox(height: 20),
    ],
  ]);
  Widget _alerts() {
    final alerts = _records('alerts');
    return _page([
      _heading(
        'Safety Alerts',
        'Alerts saved here appear in the dispatch workspace. This does not contact emergency services.',
      ),
      if (_driver)
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            onPressed: _alert,
            icon: const Icon(Icons.warning_amber),
            label: const Text('Send Alert'),
          ),
        ),
      const SizedBox(height: 16),
      if (alerts.isEmpty) _empty('No safety alerts.'),
      for (final a in alerts)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${_status(a['kind'])} • ${a['call_number']} • ${a['driver_name']}',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                Text(_date(a['created_at'])),
                if (a['notes'].toString().isNotEmpty) Text(a['notes']),
                Text(
                  a['resolved_at'] != null
                      ? 'Resolved ${_date(a['resolved_at'])}'
                      : a['acknowledged_at'] != null
                      ? 'Acknowledged ${_date(a['acknowledged_at'])}'
                      : 'Awaiting acknowledgement',
                ),
                if (!_driver && a['resolved_at'] == null)
                  Wrap(
                    spacing: 10,
                    children: [
                      if (a['acknowledged_at'] == null)
                        FilledButton(
                          onPressed: () =>
                              _perform('alerts/${a['id']}/acknowledge/'),
                          child: const Text('Acknowledge'),
                        ),
                      OutlinedButton(
                        onPressed: () => _perform('alerts/${a['id']}/resolve/'),
                        child: const Text('Resolve'),
                      ),
                    ],
                  ),
              ],
            ),
          ),
        ),
    ]);
  }
}

class _Field {
  const _Field(
    this.key,
    this.label, {
    this.required = true,
    this.money = false,
    this.choices,
    this.value,
  });
  final String key;
  final String label;
  final bool required;
  final bool money;
  final Map<String, String>? choices;
  final String? value;
  _Field withValue(String? v) => _Field(
    key,
    label,
    required: required,
    money: money,
    choices: choices,
    value: v,
  );
}

class _RecordForm extends StatefulWidget {
  const _RecordForm({required this.title, required this.fields});
  final String title;
  final List<_Field> fields;
  @override
  State<_RecordForm> createState() => _RecordFormState();
}

class _RecordFormState extends State<_RecordForm> {
  final _key = GlobalKey<FormState>();
  final Map<String, TextEditingController> _controllers = {};
  final Map<String, String?> _choices = {};
  @override
  void initState() {
    super.initState();
    for (final f in widget.fields) {
      if (f.choices != null) {
        _choices[f.key] = f.value;
      } else {
        _controllers[f.key] = TextEditingController(text: f.value);
      }
    }
  }

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.title),
    content: SizedBox(
      width: 460,
      child: SingleChildScrollView(
        child: Form(
          key: _key,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final f in widget.fields)
                Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: f.choices != null
                      ? DropdownButtonFormField<String>(
                          initialValue: _choices[f.key],
                          isExpanded: true,
                          decoration: InputDecoration(
                            labelText: f.label,
                            border: const OutlineInputBorder(),
                          ),
                          items: [
                            for (final e in f.choices!.entries)
                              DropdownMenuItem(
                                value: e.key,
                                child: Text(
                                  e.value,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                          ],
                          onChanged: (v) => _choices[f.key] = v,
                          validator: (v) => f.required && v == null
                              ? 'Choose an option.'
                              : null,
                        )
                      : TextFormField(
                          controller: _controllers[f.key],
                          keyboardType: f.money
                              ? const TextInputType.numberWithOptions(
                                  decimal: true,
                                )
                              : TextInputType.text,
                          decoration: InputDecoration(
                            labelText: f.label,
                            border: const OutlineInputBorder(),
                          ),
                          validator: (v) {
                            if (f.required && (v == null || v.trim().isEmpty)) {
                              return 'This field is required.';
                            }
                            if (f.money &&
                                !RegExp(r'^\d{1,8}(\.\d{1,2})?$')
                                    .hasMatch(v!.trim())) {
                              return 'Enter a non-negative amount with up to two decimal places.';
                            }
                            return null;
                          },
                        ),
                ),
            ],
          ),
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      FilledButton(
        onPressed: () {
          if (!_key.currentState!.validate()) return;
          Navigator.pop(context, <String, dynamic>{
            for (final f in widget.fields)
              f.key: f.choices != null
                  ? _choices[f.key]
                  : _controllers[f.key]!.text.trim(),
          });
        },
        child: const Text('Save'),
      ),
    ],
  );
}

class _TripForm extends StatefulWidget {
  const _TripForm();
  @override
  State<_TripForm> createState() => _TripFormState();
}

class _TripFormState extends State<_TripForm> {
  final _key = GlobalKey<FormState>();
  final _pickup = TextEditingController();
  final _dropoff = TextEditingController();
  final _notes = TextEditingController();
  DateTime? _scheduled;
  @override
  void dispose() {
    _pickup.dispose();
    _dropoff.dispose();
    _notes.dispose();
    super.dispose();
  }

  Future<void> _schedule() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: _scheduled ?? now,
      firstDate: DateTime(now.year, now.month, now.day),
      lastDate: DateTime(now.year + 2),
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(_scheduled ?? now),
    );
    if (time != null && mounted) {
      setState(
        () => _scheduled = DateTime(
          date.year,
          date.month,
          date.day,
          time.hour,
          time.minute,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Create Call / Reservation'),
    content: SizedBox(
      width: 500,
      child: SingleChildScrollView(
        child: Form(
          key: _key,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final f in [
                (_pickup, 'Pickup address'),
                (_dropoff, 'Drop-off address'),
                (_notes, 'Notes'),
              ])
                Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: TextFormField(
                    controller: f.$1,
                    maxLength: f.$1 == _notes ? 5000 : 255,
                    decoration: InputDecoration(
                      labelText: f.$2,
                      border: const OutlineInputBorder(),
                    ),
                    validator: (v) =>
                        f.$1 != _notes && (v == null || v.trim().isEmpty)
                        ? 'Enter an address.'
                        : null,
                  ),
                ),
              ListTile(
                title: Text(
                  _scheduled == null
                      ? 'Pickup now'
                      : 'Pickup: ${_scheduled!.toString().substring(0, 16)}',
                ),
                subtitle: const Text(
                  'Scheduled times use this device’s time zone.',
                ),
                trailing: const Icon(Icons.event),
                onTap: _schedule,
              ),
              if (_scheduled != null)
                TextButton(
                  onPressed: () => setState(() => _scheduled = null),
                  child: const Text('Use Pickup Now'),
                ),
            ],
          ),
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      FilledButton(
        onPressed: () {
          if (!_key.currentState!.validate()) return;
          if (_scheduled != null && _scheduled!.isBefore(DateTime.now())) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('Choose a future reservation time.'),
              ),
            );
            return;
          }
          Navigator.pop(context, <String, dynamic>{
            'pick_up_location': _pickup.text.trim(),
            'drop_off_location': _dropoff.text.trim(),
            'trip_notes': _notes.text.trim(),
            if (_scheduled != null)
              'pickup_time': _scheduled!.toUtc().toIso8601String(),
          });
        },
        child: const Text('Create Call'),
      ),
    ],
  );
}
