class AppUser {
  const AppUser({
    required this.username,
    required this.firstName,
    required this.lastName,
    required this.role,
    required this.roleDisplay,
    required this.mustChangePassword,
  });

  final String username;
  final String firstName;
  final String lastName;
  final String role;
  final String roleDisplay;
  final bool mustChangePassword;

  String get fullName => '$firstName $lastName'.trim();

  factory AppUser.fromJson(Map<String, dynamic> json) {
    return AppUser(
      username: json['username'] as String,
      firstName: json['first_name'] as String,
      lastName: json['last_name'] as String,
      role: json['role'] as String,
      roleDisplay: json['role_display'] as String,
      mustChangePassword: json['must_change_password'] as bool,
    );
  }
}
