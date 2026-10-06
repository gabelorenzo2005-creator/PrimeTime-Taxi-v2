import 'dart:convert';

import 'package:app/models/app_user.dart';
import 'package:app/screens/operations_dashboard.dart';
import 'package:app/services/api_client.dart';
import 'package:app/services/location_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> account(String role) => {
  'username': 'gabriellorenzo',
  'first_name': 'Gabriel',
  'last_name': 'Lorenzo',
  'role': role,
  'role_display': role == 'IT' ? 'Technician' : role,
  'must_change_password': false,
};
Map<String, dynamic> data(
  String actualRole, {
  bool access = false,
  String? preview,
}) => {
  'user': {...account(actualRole), 'development_dashboard_access': access},
  'view_as_role': preview,
  'driver_id': preview == 'DRIVER' ? 1 : null,
  'trips': [],
  'shifts': preview == 'DRIVER'
      ? [
          {
            'id': 1,
            'driver': 1,
            'shift_number': 1001,
            'car_number': '1',
            'start_time': DateTime.now().toUtc().toIso8601String(),
            'end_time': null,
          },
        ]
      : [],
  'alerts': [],
  'drivers': [],
  'owners': [],
  'vehicles': [],
};

class CountingLocation implements DriverLocationService {
  @override
  final status = ValueNotifier<String>('Tracking off');
  int starts = 0;
  @override
  Future<void> start(int id, DateTime time) async {
    starts++;
  }

  @override
  Future<void> stop() async {}
}

void main() {
  tearDown(() => ApiClient.token = null);
  for (final role in ['DRIVER', 'DISPATCHER', 'ADMIN', 'IT']) {
    testWidgets('ordinary $role cannot open developer dashboard controls', (
      tester,
    ) async {
      await http.runWithClient(
        () async {
          ApiClient.token = 'ordinary-test-token';
          await tester.pumpWidget(
            MaterialApp(
              home: OperationsDashboard(
                user: AppUser.fromJson(account(role)),
                locationService: CountingLocation(),
              ),
            ),
          );
          await tester.pumpAndSettle();
          expect(find.text('View Dashboard As'), findsNothing);
          expect(find.byKey(const ValueKey('view-dashboard-as')), findsNothing);
          expect(find.textContaining('DEVELOPMENT ACCESS'), findsNothing);
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient((request) async {
          expect(request.url.path, '/api/workspace/');
          return http.Response(jsonEncode(data(role)), 200);
        }),
      );
    });
  }

  testWidgets(
    'authorized developer previews all roles without changing identity or starting GPS',
    (tester) async {
      final user = AppUser.fromJson(account('IT'));
      final location = CountingLocation();
      final previews = <String>[];
      await http.runWithClient(
        () async {
          ApiClient.token = 'developer-test-token';
          await tester.pumpWidget(
            MaterialApp(
              home: OperationsDashboard(user: user, locationService: location),
            ),
          );
          await tester.pumpAndSettle();
          expect(find.text('View Dashboard As'), findsOneWidget);
          for (final label in ['Driver', 'Dispatcher', 'Admin']) {
            await tester.tap(find.byKey(const ValueKey('view-dashboard-as')));
            await tester.pumpAndSettle();
            await tester.tap(find.text(label).last);
            await tester.pumpAndSettle();
            expect(
              find.text(
                'Viewing $label dashboard • API permissions remain Technician',
              ),
              findsOneWidget,
            );
            expect(find.text('Return to Technician'), findsOneWidget);
            expect(user.role, 'IT');
            expect(ApiClient.token, 'developer-test-token');
            expect(location.starts, 0);
          }
          await tester.tap(find.text('Return to Technician'));
          await tester.pumpAndSettle();
          expect(
            find.text(
              'Viewing Technician dashboard • API permissions remain Technician',
            ),
            findsOneWidget,
          );
          expect(find.text('Return to Technician'), findsNothing);
          expect(previews, ['DRIVER', 'DISPATCHER', 'ADMIN', 'IT']);
          expect(location.starts, 0);
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient((request) async {
          expect(
            request.headers['Authorization'],
            'Token developer-test-token',
          );
          expect(request.method, 'GET');
          if (request.url.path == '/api/development/dashboard/') {
            final role = request.url.queryParameters['role']!;
            previews.add(role);
            return http.Response(
              jsonEncode(data('IT', access: true, preview: role)),
              200,
            );
          }
          expect(request.url.path, '/api/workspace/');
          return http.Response(jsonEncode(data('IT', access: true)), 200);
        }),
      );
    },
  );

  testWidgets(
    'server denial revokes preview UI even if earlier capability was enabled',
    (tester) async {
      var denied = false;
      await http.runWithClient(
        () async {
          ApiClient.token = 'developer-test-token';
          await tester.pumpWidget(
            MaterialApp(
              home: OperationsDashboard(user: AppUser.fromJson(account('IT'))),
            ),
          );
          await tester.pumpAndSettle();
          await tester.tap(find.byKey(const ValueKey('view-dashboard-as')));
          await tester.pumpAndSettle();
          await tester.tap(find.text('Driver').last);
          await tester.pumpAndSettle();
          expect(denied, true);
          expect(find.text('View Dashboard As'), findsNothing);
          expect(find.text('Clock In'), findsNothing);
          expect(
            find.textContaining('Development preview disabled'),
            findsOneWidget,
          );
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient((request) async {
          if (request.url.path == '/api/development/dashboard/') {
            denied = true;
            return http.Response(
              jsonEncode({'detail': 'Development preview disabled'}),
              403,
            );
          }
          return http.Response(jsonEncode(data('IT', access: !denied)), 200);
        }),
      );
    },
  );
}
