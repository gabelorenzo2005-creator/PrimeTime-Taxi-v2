import 'package:flutter_test/flutter_test.dart';
import 'package:app/main.dart';

void main() {
  testWidgets('Login rejects blank credentials before contacting server', (tester) async {
    await tester.pumpWidget(const PrimeTimeTaxiApp());
    expect(find.text('Prime Time Taxi'), findsOneWidget);
    await tester.tap(find.text('Sign In'));
    await tester.pump();
    expect(find.text('Enter your username.'), findsOneWidget);
    expect(find.text('Enter your password.'), findsOneWidget);
    expect(find.text('Signing in…'), findsNothing);
  });
}
