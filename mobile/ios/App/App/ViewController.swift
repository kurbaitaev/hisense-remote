import UIKit
import Capacitor

/// Main bridge view controller.
///
/// Plugins that live inside this app target (not installed from npm) are not
/// picked up by `npx cap sync` — it only writes npm plugins into
/// `packageClassList`. They must be registered here instead, otherwise
/// `window.Capacitor.Plugins.RokuDiscover` is undefined at runtime.
class ViewController: CAPBridgeViewController {

    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(RokuDiscoverPlugin())
    }
}
