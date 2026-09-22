import UIKit
import Capacitor

/// UIScene lifecycle. Apps built against the iOS 27 SDK must adopt scenes or
/// UIKit aborts them at launch on iOS 27 devices. The window and root
/// `ViewController` (which registers RokuDiscoverPlugin) still come from
/// Main.storyboard via `UISceneStoryboardFile`; this delegate only forwards
/// URL / universal-link events to Capacitor's SceneDelegateProxy.
class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}
