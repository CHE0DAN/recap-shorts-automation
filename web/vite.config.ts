import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import fs from "node:fs";
import path from "node:path";

// 개발 서버에서만: 백엔드가 없어도 ?mock=1 화면이 실제 작업 폴더의 이미지·소리·영상을 보여 주도록
// /media/<작업>/<경로> 를 ../work/<작업>/<경로> 로, /fonts/<파일> 을 ../assets/fonts/<파일> 로 직접 제공한다.
// (실제 백엔드는 같은 경로를 제공하므로 운영에서는 이 플러그인이 쓰이지 않는다.)
function localMedia(): Plugin {
  const root = path.resolve(import.meta.dirname, "..");
  const types: Record<string, string> = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".wav": "audio/wav", ".mp4": "video/mp4", ".json": "application/json", ".txt": "text/plain; charset=utf-8", ".otf": "font/otf",
  };
  return {
    name: "local-media",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = decodeURIComponent((req.url || "").split("?")[0]);
        let file: string | null = null;
        if (url.startsWith("/media/")) file = path.join(root, "work", url.slice(7));
        else if (url.startsWith("/fonts/")) file = path.join(root, "assets", "fonts", url.slice(7));
        if (!file || !file.startsWith(root) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return next();
        const size = fs.statSync(file).size;
        const type = types[path.extname(file).toLowerCase()] || "application/octet-stream";
        const range = req.headers.range;
        if (range) {
          const m = /bytes=(\d*)-(\d*)/.exec(range);
          const start = m && m[1] ? parseInt(m[1]) : 0;
          const end = m && m[2] ? parseInt(m[2]) : size - 1;
          res.writeHead(206, { "Content-Type": type, "Accept-Ranges": "bytes", "Content-Range": `bytes ${start}-${end}/${size}`, "Content-Length": end - start + 1 });
          fs.createReadStream(file, { start, end }).pipe(res);
        } else {
          res.writeHead(200, { "Content-Type": type, "Accept-Ranges": "bytes", "Content-Length": size });
          fs.createReadStream(file).pipe(res);
        }
      });
    },
  };
}

const api = "http://127.0.0.1:8020";
export default defineConfig({
  plugins: [react(), tailwindcss(), localMedia()],
  base: "/",
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { port: 5173, proxy: { "/api": api, "/media": api, "/fonts": api } },
  preview: { port: 4173, proxy: { "/api": api, "/media": api, "/fonts": api } },
});
