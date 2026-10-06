import 'dart:convert';

import 'package:app/main.dart';
import 'package:app/models/app_user.dart';
import 'package:app/screens/operations_dashboard.dart';
import 'package:app/services/api_client.dart';
import 'package:app/services/location_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> userJson(String role, {bool requiredChange = false}) => {
  'username': 'tester',
  'first_name': 'Test',
  'last_name': 'User',
  'role': role,
  'role_display': role,
  'must_change_password': requiredChange,
};
Map<String, dynamic> workspace(String role) => {
  'user': userJson(role),
  'driver_id': role == 'DRIVER' ? 1 : null,
  'trips': [],
  'shifts': [],
  'alerts': [],
  'drivers': [],
  'owners': [],
  'vehicles': [
    {
      'id': 1,
      'car_number': '1',
      'license_plate_number': 'TEST001',
      'owner': 1,
      'owner_name': 'Company',
    },
  ],
};

class TestTracking implements DriverLocationService {
  @override
  final status = ValueNotifier<String>('Tracking off');
  int? shift;
  @override
  Future<void> start(int id, DateTime startedAt) async {
    shift = id;
  }

  @override
  Future<void> stop() async {
    shift = null;
  }
}

void main() {
  tearDown(() => ApiClient.token = null);
  for (final role in ['DRIVER', 'DISPATCHER', 'ADMIN', 'IT']) {
    testWidgets('$role sees the correct server-backed actions', (tester) async {
      await http.runWithClient(
        () async {
          ApiClient.token = 'test-token';
          await tester.pumpWidget(
            MaterialApp(
              home: OperationsDashboard(user: AppUser.fromJson(userJson(role))),
            ),
          );
          await tester.pumpAndSettle();
          expect(find.text('Welcome, Test User'), findsOneWidget);
          expect(
            find.text('Create Call / Reservation'),
            ['DISPATCHER', 'ADMIN'].contains(role)
                ? findsOneWidget
                : findsNothing,
          );
          expect(
            find.text('Clock In'),
            role == 'DRIVER' ? findsOneWidget : findsNothing,
          );
          expect(
            find.text('Management'),
            ['ADMIN', 'IT'].contains(role) ? findsOneWidget : findsNothing,
          );
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient((request) async {
          expect(request.headers['Authorization'], 'Token test-token');
          return http.Response(jsonEncode(workspace(role)), 200);
        }),
      );
    });
  }

  testWidgets(
    'Driver clock-in posts the selected vehicle and shows server-confirmed shift',
    (tester) async {
      final data = workspace('DRIVER');
      var posts = 0;
      final tracking = TestTracking();
      await http.runWithClient(
        () async {
          ApiClient.token = 'test-token';
          await tester.pumpWidget(
            MaterialApp(
              home: OperationsDashboard(
                user: AppUser.fromJson(userJson('DRIVER')),
                locationService: tracking,
              ),
            ),
          );
          await tester.pumpAndSettle();
          await tester.ensureVisible(find.text('Clock In'));
          await tester.pumpAndSettle();
          await tester.tap(find.text('Clock In'));
          await tester.pumpAndSettle();
          await tester.tap(find.byType(DropdownButtonFormField<String>));
          await tester.pumpAndSettle();
          await tester.tap(find.text('Car 1 • TEST001').last);
          await tester.pumpAndSettle();
          await tester.tap(find.text('Save'));
          await tester.pumpAndSettle();
          expect(posts, 1);
          expect(tracking.shift, 1);
          expect(find.text('Shift 1001 • Car 1'), findsOneWidget);
          expect(find.text('Clock Out'), findsOneWidget);
          await tester.ensureVisible(find.text('Clock Out'));
          await tester.pumpAndSettle();
          await tester.tap(find.text('Clock Out'));
          await tester.pumpAndSettle();
          await tester.enterText(find.byType(TextFormField), '100');
          await tester.tap(find.text('Save'));
          await tester.pumpAndSettle();
          expect(tracking.shift, isNull);
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient((request) async {
          if (request.url.path == '/api/shifts/') {
            posts++;
            expect(jsonDecode(request.body), {'vehicle_id': 1});
            data['shifts'] = [
              {
                'id': 1,
                'shift_number': 1001,
                'driver': 1,
                'driver_name': 'Test User',
                'call_number': 'D1',
                'vehicle': 1,
                'car_number': '1',
                'start_time': DateTime.now().toUtc().toIso8601String(),
                'end_time': null,
              },
            ];
            return http.Response(
              jsonEncode((data['shifts'] as List).single),
              201,
            );
          }
          if (request.url.path == '/api/shifts/1/end/') {
            expect(jsonDecode(request.body), {'amount': '100'});
            data['shifts'] = [];
            return http.Response('{}', 200);
          }
          return http.Response(jsonEncode(data), 200);
        }),
      );
    },
  );

  testWidgets('Required password reset does not open operations early', (
    tester,
  ) async {
    await http.runWithClient(
      () async {
        await tester.pumpWidget(const PrimeTimeTaxiApp());
        await tester.enterText(find.byType(TextFormField).at(0), 'tester');
        await tester.enterText(find.byType(TextFormField).at(1), 'oldpassword');
        await tester.tap(find.text('Sign In'));
        await tester.pumpAndSettle();
        expect(find.text('Change Password'), findsOneWidget);
        expect(find.text('Welcome, Test User'), findsNothing);
        await tester.pumpWidget(const SizedBox());
      },
      () => MockClient((request) async {
        expect(request.url.path, '/api/login/');
        return http.Response(
          jsonEncode({
            ...userJson('DRIVER', requiredChange: true),
            'token': 'test-token',
          }),
          200,
        );
      }),
    );
  });
}
