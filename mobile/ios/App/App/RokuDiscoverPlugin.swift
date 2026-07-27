import Foundation
import Capacitor
import Darwin

/**
 Roku discovery — same protocol as official remotes & open-source projects
 (Roam, RoMote, matthewdowney/roku):

   1. SSDP M-SEARCH → 239.255.255.250:1900  ST: roku:ecp
   2. Parse LOCATION: http://IP:8060/
   3. Optional: GET /query/device-info for friendly name
   4. Fallback: HTTP probe of this phone's /24 on port 8060

 Requires NSLocalNetworkUsageDescription + user Allow on first run.
 */
@objc(RokuDiscoverPlugin)
public class RokuDiscoverPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "RokuDiscoverPlugin"
    public let jsName = "RokuDiscover"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "scan", returnType: CAPPluginReturnPromise),
    ]

    @objc func scan(_ call: CAPPluginCall) {
        DispatchQueue.global(qos: .userInitiated).async {
            // 1) SSDP (primary — how real apps find Rokus)
            var byIp: [String: [String: String]] = [:]
            for item in Self.ssdpDiscover(timeout: 3.0) {
                if let ip = item["ip"] { byIp[ip] = item }
            }

            // 2) HTTP subnet always merges (catches TVs that miss multicast)
            for item in Self.subnetScan(timeoutPerHost: 0.4) {
                if let ip = item["ip"], byIp[ip] == nil {
                    byIp[ip] = item
                }
            }

            var tvs = Array(byIp.values)
            tvs = tvs.map { item in
                var copy = item
                let ip = copy["ip"] ?? ""
                if let name = Self.fetchName(ip: ip, timeout: 0.8) {
                    copy["name"] = name
                } else if (copy["name"] ?? "").isEmpty {
                    copy["name"] = "Roku TV"
                }
                return copy
            }
            tvs.sort { ($0["ip"] ?? "") < ($1["ip"] ?? "") }
            call.resolve(["tvs": tvs])
        }
    }

    // MARK: - SSDP M-SEARCH (roku:ecp)

    private static func ssdpDiscover(timeout: TimeInterval) -> [[String: String]] {
        var found: [[String: String]] = []
        var seen = Set<String>()

        let sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard sock >= 0 else { return [] }
        defer { close(sock) }

        var reuse: Int32 = 1
        setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout.size(ofValue: reuse)))

        var ttl: UInt8 = 4
        setsockopt(sock, IPPROTO_IP, IP_MULTICAST_TTL, &ttl, socklen_t(MemoryLayout.size(ofValue: ttl)))

        // Non-blocking-ish receive timeout
        var tv = timeval(tv_sec: 0, tv_usec: 250_000)
        setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout.size(ofValue: tv)))

        // Official ECP discovery string (Roku External Control API)
        let msearch =
            "M-SEARCH * HTTP/1.1\r\n" +
            "HOST: 239.255.255.250:1900\r\n" +
            "MAN: \"ssdp:discover\"\r\n" +
            "MX: 3\r\n" +
            "ST: roku:ecp\r\n" +
            "USER-AGENT: TVRemote/1.0 UPnP/1.1 iOS\r\n" +
            "\r\n"

        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = UInt16(1900).bigEndian
        addr.sin_addr.s_addr = inet_addr("239.255.255.250")

        // Send M-SEARCH a few times (multicast is lossy — same as Java RokuScan tools)
        for _ in 0..<3 {
            msearch.withCString { ptr in
                withUnsafePointer(to: &addr) { ap in
                    ap.withMemoryRebound(to: sockaddr.self, capacity: 1) { sap in
                        _ = sendto(sock, ptr, strlen(ptr), 0, sap, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }
            usleep(80_000)
        }

        let deadline = Date().addingTimeInterval(timeout)
        var buf = [UInt8](repeating: 0, count: 8192)

        while Date() < deadline {
            let n = recv(sock, &buf, buf.count, 0)
            if n <= 0 { continue }
            let text = String(bytes: buf[0..<Int(n)], encoding: .utf8) ?? ""
            guard text.uppercased().contains("ROKU") || text.lowercased().contains("roku:ecp")
                    || text.lowercased().contains("location:") else { continue }

            if let ip = parseLocationIp(text), !seen.contains(ip) {
                seen.insert(ip)
                found.append(["ip": ip, "name": "Roku TV", "via": "ssdp"])
            }
        }
        return found
    }

    /// Parse LOCATION: http://192.168.x.x:8060/ from SSDP response
    private static func parseLocationIp(_ response: String) -> String? {
        for raw in response.split(whereSeparator: { $0 == "\r" || $0 == "\n" }) {
            let line = String(raw)
            let upper = line.uppercased()
            guard upper.hasPrefix("LOCATION:") else { continue }
            // drop "LOCATION:"
            let value = line.dropFirst(9).trimmingCharacters(in: .whitespaces)
            if let url = URL(string: value), let host = url.host {
                let parts = host.split(separator: ".")
                if parts.count == 4, parts.allSatisfy({ Int($0) != nil }) {
                    return host
                }
            }
            // fallback regex
            if let r = value.range(of: #"\b(\d{1,3}\.){3}\d{1,3}\b"#, options: .regularExpression) {
                return String(value[r])
            }
        }
        return nil
    }

    // MARK: - Subnet HTTP (native URLSession — no browser CORS)

    private static func localIPv4Prefix() -> String? {
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let first = ifaddr else { return nil }
        defer { freeifaddrs(ifaddr) }

        var ptr: UnsafeMutablePointer<ifaddrs>? = first
        while let p = ptr {
            defer { ptr = p.pointee.ifa_next }
            let flags = Int32(p.pointee.ifa_flags)
            guard flags & (IFF_UP | IFF_RUNNING) == (IFF_UP | IFF_RUNNING) else { continue }
            guard flags & IFF_LOOPBACK == 0 else { continue }
            guard p.pointee.ifa_addr.pointee.sa_family == UInt8(AF_INET) else { continue }

            var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            getnameinfo(
                p.pointee.ifa_addr,
                socklen_t(p.pointee.ifa_addr.pointee.sa_len),
                &hostname,
                socklen_t(hostname.count),
                nil,
                0,
                NI_NUMERICHOST
            )
            let ip = String(cString: hostname)
            if ip.hasPrefix("192.168.") || ip.hasPrefix("10.") {
                let parts = ip.split(separator: ".")
                if parts.count == 4 {
                    return "\(parts[0]).\(parts[1]).\(parts[2])"
                }
            }
        }
        return nil
    }

    private static func subnetScan(timeoutPerHost: TimeInterval) -> [[String: String]] {
        guard let pre = localIPv4Prefix() else { return [] }
        var found: [[String: String]] = []
        let lock = NSLock()

        // Typical home DHCP ends first
        var order: [Int] = [
            100, 101, 102, 103, 150, 151, 152, 153, 154, 155, 160,
            10, 11, 20, 50, 2, 3, 4, 5, 1, 254, 200, 110, 120,
        ]
        for i in 1..<255 where !order.contains(i) { order.append(i) }

        let group = DispatchGroup()
        let queue = DispatchQueue(label: "roku.http.scan", attributes: .concurrent)
        let sem = DispatchSemaphore(value: 40)

        for n in order {
            group.enter()
            sem.wait()
            queue.async {
                defer { sem.signal(); group.leave() }
                let ip = "\(pre).\(n)"
                if let name = fetchName(ip: ip, timeout: timeoutPerHost) {
                    lock.lock()
                    found.append(["ip": ip, "name": name, "via": "http"])
                    lock.unlock()
                }
            }
        }
        _ = group.wait(timeout: .now() + 14)
        return found
    }

    private static func fetchName(ip: String, timeout: TimeInterval = 0.6) -> String? {
        guard let url = URL(string: "http://\(ip):8060/query/device-info") else { return nil }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = "GET"
        request.cachePolicy = .reloadIgnoringLocalCacheData

        let sem = DispatchSemaphore(value: 0)
        var result: String?
        URLSession.shared.dataTask(with: request) { data, response, _ in
            defer { sem.signal() }
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let data = data,
                  let text = String(data: data, encoding: .utf8),
                  text.contains("device-info") || text.lowercased().contains("roku")
            else { return }
            result = firstMatch(text, pattern: "<friendly-device-name>([^<]+)")
                ?? firstMatch(text, pattern: "<user-device-name>([^<]+)")
                ?? firstMatch(text, pattern: "<model-name>([^<]+)")
                ?? "Roku TV"
        }.resume()
        _ = sem.wait(timeout: .now() + timeout + 0.25)
        return result
    }

    private static func firstMatch(_ text: String, pattern: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        guard let match = regex.firstMatch(in: text, range: range),
              match.numberOfRanges > 1,
              let r = Range(match.range(at: 1), in: text) else { return nil }
        return String(text[r]).trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
