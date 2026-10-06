import Flutter
import UIKit
import UserNotifications

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var pushChannel: FlutterMethodChannel?
  private var pendingRegistration: FlutterResult?
  private var deviceToken: String?

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    guard let registrar = engineBridge.pluginRegistry.registrar(forPlugin: "PrimeTimeAPNs") else { return }
    let channel = FlutterMethodChannel(name: "primetime/apns", binaryMessenger: registrar.messenger())
    pushChannel = channel
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self = self else { return }
      guard call.method == "register" else { result(FlutterMethodNotImplemented); return }
      UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, _ in
        DispatchQueue.main.async {
          guard granted else { result(nil); return }
          if let token = self.deviceToken { result(self.tokenInfo(token)); return }
          guard self.pendingRegistration == nil else {
            result(FlutterError(code: "busy", message: "Registration is in progress", details: nil)); return
          }
          self.pendingRegistration = result
          UIApplication.shared.registerForRemoteNotifications()
          DispatchQueue.main.asyncAfter(deadline: .now() + 20) {
            if let pending = self.pendingRegistration {
              self.pendingRegistration = nil
              pending(FlutterError(code: "timeout", message: "APNs registration unavailable", details: nil))
            }
          }
        }
      }
    }
  }

  private func tokenInfo(_ token: String) -> [String: String] {
    return ["token": token, "topic": Bundle.main.bundleIdentifier ?? "",
            "environment": Bundle.main.object(forInfoDictionaryKey: "PrimeTimeAPNSEnvironment") as? String ?? ""]
  }

  override func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken token: Data) {
    super.application(application, didRegisterForRemoteNotificationsWithDeviceToken: token)
    deviceToken = token.map { String(format: "%02x", $0) }.joined()
    if let pending = pendingRegistration {
      pendingRegistration = nil
      pending(tokenInfo(deviceToken!))
    } else {
      pushChannel?.invokeMethod("tokenChanged", arguments: nil)
    }
  }

  override func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
    super.application(application, didFailToRegisterForRemoteNotificationsWithError: error)
    if let pending = pendingRegistration {
      pendingRegistration = nil
      pending(FlutterError(code: "registration", message: "APNs registration unavailable", details: nil))
    }
  }
}
