// Same-origin gateway like the Railway Caddy service: /api /ws /health -> API, rest -> web.
import http from "node:http";
import net from "node:net";
const API = { host: "127.0.0.1", port: 8000 }, WEB = { host: "127.0.0.1", port: 3000 };
const pick = (url) => (/^\/(api|ws|health)\//.test(url) ? API : url === "/metrics" ? null : WEB);
const server = http.createServer((req, res) => {
  const t = pick(req.url);
  if (!t) { res.writeHead(404).end(); return; }
  const p = http.request({ ...t, path: req.url, method: req.method,
    headers: { ...req.headers, "x-forwarded-proto": "http", "x-forwarded-for": req.socket.remoteAddress } }, (r) => {
    res.writeHead(r.statusCode, r.headers); r.pipe(res);
  });
  p.on("error", () => { if (!res.headersSent) res.writeHead(502); res.end(); });
  req.pipe(p);
});
server.on("upgrade", (req, sock, head) => {
  const t = pick(req.url);
  if (!t) { sock.destroy(); return; }
  const up = net.connect(t.port, t.host, () => {
    up.write(`${req.method} ${req.url} HTTP/1.1\r\n` +
      Object.entries(req.headers).map(([k, v]) => `${k}: ${v}`).join("\r\n") + "\r\n\r\n");
    if (head?.length) up.write(head);
    sock.pipe(up).pipe(sock);
  });
  up.on("error", () => sock.destroy());
  sock.on("error", () => up.destroy());
});
server.listen(8080, () => console.log("gateway :8080"));
