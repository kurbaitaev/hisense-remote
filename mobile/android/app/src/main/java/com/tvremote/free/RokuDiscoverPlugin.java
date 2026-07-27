package com.tvremote.free;

import android.content.Context;
import android.net.wifi.WifiManager;
import android.util.Log;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Same discovery path as open-source Roku remotes (SSDP roku:ecp + HTTP :8060).
 * MulticastLock required on Android (RoMote / matthewdowney pattern).
 */
@CapacitorPlugin(name = "RokuDiscover")
public class RokuDiscoverPlugin extends Plugin {
    private static final String TAG = "RokuDiscover";
    private static final String MSEARCH =
            "M-SEARCH * HTTP/1.1\r\n" +
            "HOST: 239.255.255.250:1900\r\n" +
            "MAN: \"ssdp:discover\"\r\n" +
            "MX: 2\r\n" +
            "ST: roku:ecp\r\n" +
            "\r\n";

    @PluginMethod
    public void scan(PluginCall call) {
        getBridge().execute(new Runnable() {
            @Override
            public void run() {
                WifiManager wifi = (WifiManager) getContext().getApplicationContext()
                        .getSystemService(Context.WIFI_SERVICE);
                WifiManager.MulticastLock lock = null;
                if (wifi != null) {
                    lock = wifi.createMulticastLock("roku-ssdp");
                    lock.setReferenceCounted(true);
                    lock.acquire();
                }
                try {
                    Map<String, JSObject> byIp = new LinkedHashMap<>();
                    for (JSObject t : ssdpDiscover(3500)) {
                        byIp.put(t.getString("ip"), t);
                    }
                    for (JSObject t : subnetScan()) {
                        byIp.putIfAbsent(t.getString("ip"), t);
                    }
                    JSArray arr = new JSArray();
                    for (JSObject t : byIp.values()) {
                        String ip = t.getString("ip");
                        String name = fetchName(ip);
                        if (name != null) t.put("name", name);
                        arr.put(t);
                    }
                    JSObject ret = new JSObject();
                    ret.put("tvs", arr);
                    call.resolve(ret);
                } catch (Exception e) {
                    Log.e(TAG, "scan failed", e);
                    call.reject("scan failed: " + e.getMessage());
                } finally {
                    if (lock != null && lock.isHeld()) lock.release();
                }
            }
        });
    }

    @PluginMethod
    public void probe(PluginCall call) {
        String ip = call.getString("ip");
        if (ip == null || ip.isEmpty()) {
            call.reject("ip required");
            return;
        }
        getBridge().execute(() -> {
            String name = fetchName(ip);
            JSObject ret = new JSObject();
            ret.put("ok", name != null);
            ret.put("ip", ip);
            if (name != null) ret.put("name", name);
            call.resolve(ret);
        });
    }

    private List<JSObject> ssdpDiscover(int timeoutMs) {
        List<JSObject> found = new ArrayList<>();
        try {
            DatagramSocket socket = new DatagramSocket(null);
            socket.setReuseAddress(true);
            socket.bind(new InetSocketAddress(0));
            socket.setSoTimeout(300);
            socket.setBroadcast(true);

            byte[] data = MSEARCH.getBytes(StandardCharsets.UTF_8);
            InetAddress group = InetAddress.getByName("239.255.255.250");

            long deadline = System.currentTimeMillis() + timeoutMs;
            long nextResend = System.currentTimeMillis();
            byte[] buf = new byte[16384];

            while (System.currentTimeMillis() < deadline) {
                if (System.currentTimeMillis() >= nextResend) {
                    for (int i = 0; i < 2; i++) {
                        socket.send(new DatagramPacket(data, data.length, group, 1900));
                        Thread.sleep(40);
                    }
                    nextResend = System.currentTimeMillis() + 1000;
                }
                try {
                    DatagramPacket pkt = new DatagramPacket(buf, buf.length);
                    socket.receive(pkt);
                    String text = new String(pkt.getData(), 0, pkt.getLength(), StandardCharsets.UTF_8);
                    String ip = parseLocationIp(text);
                    if (ip == null && pkt.getAddress() != null) {
                        String sender = pkt.getAddress().getHostAddress();
                        if (isPrivateIPv4(sender)
                                && (text.toUpperCase().contains("ROKU")
                                || text.toLowerCase().contains("roku:ecp"))) {
                            ip = sender;
                        }
                    }
                    if (ip == null) continue;
                    boolean exists = false;
                    for (JSObject o : found) {
                        if (ip.equals(o.getString("ip"))) { exists = true; break; }
                    }
                    if (!exists) {
                        JSObject o = new JSObject();
                        o.put("ip", ip);
                        o.put("name", "Roku TV");
                        o.put("via", "ssdp");
                        found.add(o);
                    }
                } catch (SocketTimeoutException ignored) {
                }
            }
            socket.close();
        } catch (Exception e) {
            Log.w(TAG, "ssdp error", e);
        }
        return found;
    }

    private String parseLocationIp(String response) {
        for (String line : response.split("\\r?\\n")) {
            if (line.regionMatches(true, 0, "LOCATION:", 0, 9)) {
                String value = line.substring(9).trim();
                Matcher m = Pattern.compile("https?://(\\d+\\.\\d+\\.\\d+\\.\\d+)").matcher(value);
                if (m.find()) {
                    String ip = m.group(1);
                    if (isPrivateIPv4(ip)) return ip;
                }
            }
        }
        return null;
    }

    private boolean isPrivateIPv4(String ip) {
        if (ip == null) return false;
        String[] p = ip.split("\\.");
        if (p.length != 4) return false;
        try {
            int a = Integer.parseInt(p[0]);
            int b = Integer.parseInt(p[1]);
            if (a == 10) return true;
            if (a == 192 && b == 168) return true;
            if (a == 172 && b >= 16 && b <= 31) return true;
        } catch (NumberFormatException ignored) {
        }
        return false;
    }

    private String localPrefix() {
        try {
            Enumeration<NetworkInterface> en = NetworkInterface.getNetworkInterfaces();
            while (en.hasMoreElements()) {
                NetworkInterface ni = en.nextElement();
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (java.net.InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    InetAddress a = ia.getAddress();
                    if (a.isLoopbackAddress() || !(a instanceof java.net.Inet4Address)) continue;
                    String ip = a.getHostAddress();
                    if (ip != null && isPrivateIPv4(ip)) {
                        String[] p = ip.split("\\.");
                        if (p.length == 4) return p[0] + "." + p[1] + "." + p[2];
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private List<JSObject> subnetScan() {
        List<JSObject> found = Collections.synchronizedList(new ArrayList<>());
        String pre = localPrefix();
        if (pre == null) return found;

        int[] hot = {100, 101, 102, 150, 151, 152, 153, 154, 155, 160, 10, 20, 50, 2, 3, 4, 5, 1, 254, 200};
        List<Integer> order = new ArrayList<>();
        for (int n : hot) order.add(n);
        for (int i = 1; i < 255; i++) if (!order.contains(i)) order.add(i);

        ExecutorService pool = Executors.newFixedThreadPool(40);
        for (int n : order) {
            final String ip = pre + "." + n;
            pool.execute(() -> {
                String name = fetchName(ip);
                if (name != null) {
                    JSObject o = new JSObject();
                    o.put("ip", ip);
                    o.put("name", name);
                    o.put("via", "http");
                    found.add(o);
                }
            });
        }
        pool.shutdown();
        try {
            pool.awaitTermination(12, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {
        }
        return found;
    }

    private String fetchName(String ip) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL("http://" + ip + ":8060/query/device-info");
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(400);
            conn.setReadTimeout(400);
            conn.setRequestMethod("GET");
            if (conn.getResponseCode() != 200) return null;
            BufferedReader br = new BufferedReader(new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = br.readLine()) != null) sb.append(line).append('\n');
            br.close();
            String text = sb.toString();
            if (!text.contains("device-info") && !text.toLowerCase().contains("roku")) return null;
            Matcher m = Pattern.compile("<friendly-device-name>([^<]+)").matcher(text);
            if (m.find()) return m.group(1).trim();
            m = Pattern.compile("<model-name>([^<]+)").matcher(text);
            if (m.find()) return m.group(1).trim();
            return "Roku TV";
        } catch (Exception e) {
            return null;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }
}
