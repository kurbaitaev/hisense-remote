async function loadShare() {
  const res = await fetch("/api/share");
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Could not load share info");

  const guest = data.https_url || data.http_url;
  const direct = data.direct_url || data.http_url + "/direct";

  document.getElementById("guest-url").textContent = guest;
  document.getElementById("direct-url").textContent = direct;

  const qr = document.getElementById("guest-qr");
  qr.src =
    "https://api.qrserver.com/v1/create-qr-code/?size=180x180&margin=8&data=" +
    encodeURIComponent(guest);

  const st = document.getElementById("guest-status");
  if (data.tv_connected) {
    st.textContent = `TV connected · ${data.tv_host || ""} · server on ${data.lan_ip}`;
    st.classList.add("ok");
  } else if (data.tv_host) {
    st.textContent = `Server on ${data.lan_ip} — TV ${data.tv_host} not responding yet`;
  } else {
    st.textContent = `Server on ${data.lan_ip} — connect a TV on the main remote first`;
  }

  document.getElementById("copy-guest").onclick = () => copy(guest, "Guest link copied");
  document.getElementById("copy-direct").onclick = () => copy(direct, "Direct link copied");
  document.getElementById("sms-guest").onclick = () => {
    location.href = "sms:&body=" + encodeURIComponent("TV remote: " + guest);
  };
}

function copy(text, toast) {
  navigator.clipboard.writeText(text).then(() => {
    const el = document.getElementById("guest-status");
    const prev = el.textContent;
    el.textContent = toast;
    el.classList.add("ok");
    setTimeout(() => {
      el.textContent = prev;
    }, 2000);
  });
}

loadShare().catch((err) => {
  document.getElementById("guest-status").textContent = err.message;
});
