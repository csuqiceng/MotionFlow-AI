import * as net from "node:net";

/**
 * Bind an ephemeral socket on the loopback interface, read the OS-assigned
 * port, then release it. There is an inherent TOCTOU window (another process
 * could grab the port before the local server binds), but it is small and the
 * supervisor's crash-restart policy covers the rare collision.
 */
export async function pickFreePort(host = "127.0.0.1"): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, host, () => {
      const addr = srv.address();
      if (addr && typeof addr === "object") {
        const port = addr.port;
        srv.close(() => resolve(port));
      } else {
        srv.close();
        reject(new Error("could not determine free port"));
      }
    });
  });
}
