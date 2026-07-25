import Foundation
import Capacitor
import Darwin

/**
 Native Roku discovery — same approach as official remote apps:
 1) SSDP multicast M-SEARCH for roku:ecp (UDP 1900)
 2) Fallback: HTTP probe of the phone's Wi‑Fi subnet on port 8060
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
            var tvs = Self.ssdpDiscover(timeout: 2.5)
            if tvs.isEmpty {
                tvs = Self.subnetScan(timeoutPerHost: 0.35)
            }
            // Enrich names via device-info when missing
            tvs = tvs.map { item in
                var copy = item
                if (copy["name"] ?? "").isEmpty || copy["name"] == "Roku TV" {
                    if let name = Self.fetchName(ip: copy["ip"] ?? "") {
                        copy["name"] = name
                    }
                }
                return copy
            }
            call.resolve(["tvs": tvs])
        }
    }

    // MARK: - SSDP (what Roku apps use)

    private static func ssdpDiscover(timeout: TimeInterval) -> [[String: String]] {
        var found: [[String: String]] = []
        var seen = Set<String>()

        let sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard sock >= 0 else { return [] }
        defer { close(sock) }

        var reuse: Int32 = 1
        setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout.size(ofValue: reuse)))

        var ttl: UInt8 = 2
        setsockopt(sock, IPPROTO_IP, IP_MULTICAST_TTL, &ttl, socklen_t(MemoryLayout.size(ofValue: ttl)))

        var timeoutVal = timeval(tv_sec: 0, tv_usec: 300_000)
        setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &timeoutVal, socklen_t(MemoryLayout.size(ofValue: timeoutVal)))

        let msearch =
            "M-SEARCH * HTTP/1.1\r\n" +
            "HOST: 239.255.255.250:1900\r\n" +
            "MAN: \"ssdp:discover\"\r\n" +
            "MX: 2\r\n" +
            "ST: roku:ecp\r\n" +
            "\r\n"

        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(1900).bigEndian
        addr.sin_addr.s_addr = inet_addr("239.255.255.250")

        msearch.withCString { ptr in
            withUnsafePointer(to: &addr) { ap in
                ap.withMemoryRebound(to: sockaddr.self, capacity: 1) { sap in
                    _ = sendto(sock, ptr, strlen(ptr), 0, sap, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
        }

        let deadline = Date().addingTimeInterval(timeout)
        var buf = [UInt8](repeating: 0, count: 4096)

        while Date() < deadline {
            let n = recv(sock, &buf, buf.count, 0)
            if n <= 0 { continue }
            let text = String(bytes: buf[0..<n], encoding: .utf8) ?? ""
            var location: String?
            for line in text.split(whereSeparator: { $0 == "\r" || $0 == "\n" }) {
                let s = String(line)
                if s.uppercased().hasPrefix("LOCATION:") {
                    location = s.split(separator: ":", maxSplits: 1).last.map { String($0).trimmingCharacters(in: .whitespaces) }
                }
            }
            guard let loc = location, let ip = ipFromLocation(loc), !seen.contains(ip) else { continue }
            seen.insert(ip)
            found.append(["ip": ip, "name": "Roku TV", "via": "ssdp"])
        }
        return found
    }

    private static func ipFromLocation(_ location: String) -> String? {
        guard let url = URL(string: location), let host = url.host else { return nil }
        // Only IPv4 hostnames
        let parts = host.split(separator: ".")
        guard parts.count == 4, parts.allSatisfy({ Int($0) != nil }) else { return nil }
        return host
    }

    // MARK: - Subnet HTTP scan (native URLSession — no CORS)

    private static func localIPv4Prefix() -> String? {
        var address: String?
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let first = ifaddr else { return nil }
        defer { freeifaddrs(ifaddr) }

        var ptr: UnsafeMutablePointer<ifaddrs>? = first
        while let p = ptr {
            defer { ptr = p.pointee.ifa_next }
            let flags = Int32(p.pointee.ifa_flags)
            guard flags & (IFF_UP | IFF_RUNNING) == (IFF_UP | IFF_RUNNING) else { continue }
            guard flags & IFF_LOOPBACK == 0 else { continue }
            let addr = p.pointee.ifa_addr.pointee
            guard addr.sa_family == UInt8(AF_INET) else { continue }
            var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            getnameinfo(p.pointee.ifa_addr, socklen_t(addr.sa_len), &hostname, socklen_t(hostname.count), nil, 0, NI_NUMERICHOST)
            let ip = String(cString: hostname)
            if ip.hasPrefix("192.168.") || ip.hasPrefix("10.") {
                let parts = ip.split(separator: ".")
                if parts.count == 4 {
                    address = "\(parts[0]).\(parts[1]).\(parts[2])"
                    break
                }
            }
        }
        return address
    }

    private static func subnetScan(timeoutPerHost: TimeInterval) -> [[String: String]] {
        guard let pre = localIPv4Prefix() else { return [] }
        var found: [[String: String]] = []
        let lock = NSLock()

        // Priority last-octets then rest (typical DHCP)
        var order: [Int] = [100, 101, 102, 150, 151, 152, 153, 154, 155, 160, 10, 20, 50, 2, 3, 4, 5, 1, 254, 200]
        for i in 1..<255 where !order.contains(i) { order.append(i) }

        let group = DispatchGroup()
        let queue = DispatchQueue(label: "roku.scan", attributes: .concurrent)
        let sem = DispatchSemaphore(value: 32)

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
        _ = group.wait(timeout: .now() + 12)
        return found
    }

    private static func fetchName(ip: String, timeout: TimeInterval = 0.6) -> String? {
        guard let url = URL(string: "http://\(ip):8060/query/device-info") else { return nil }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = "GET"

        let sem = DispatchSemaphore(value: 0)
        var result: String?
        let task = URLSession.shared.dataTask(with: request) { data, response, _ in
            defer { sem.signal() }
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let data = data,
                  let text = String(data: data, encoding: .utf8),
                  text.contains("device-info") || text.lowercased().contains("roku")
            else { return }
            if let name = firstMatch(text, pattern: "<friendly-device-name>([^<]+)") {
                result = name
            } else if let name = firstMatch(text, pattern: "<model-name>([^<]+)") {
                result = name
            } else {
                result = "Roku TV"
            }
        }
        task.resume()
        _ = sem.wait(timeout: .now() + timeout + 0.2)
        return result
    }

    private static func firstMatch(_ text: String, pattern: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        guard let match = regex.firstMatch(in: text, range: range),
              match.numberOfRanges > 1,
              let r = Range(match.range(at: 1), in: text) else { return nil }
        return String(text[r])
    }
}
