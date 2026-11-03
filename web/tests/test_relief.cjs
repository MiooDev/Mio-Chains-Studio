const { chromium } = require("playwright");
const path = require("path");
(async () => {
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto("file://" + path.resolve(process.argv[2]));
  await page.waitForFunction(() => window.__mcp && window.__mcp.state.chains.length === 1);
  const res = await page.evaluate(async () => {
    const n = 128, nm = new Uint8Array(n * n * 4), gray = new Uint8Array(4 * 4 * 4).fill(200);
    // Normal map DirectX d'un dôme : rouge = droite, vert = BAS de l'image, bleu = Z.
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const dx = (x - n / 2 + 0.5) / (n * 0.4), dy = (y - n / 2 + 0.5) / (n * 0.4);
      const r2 = dx * dx + dy * dy;
      let nx = 0, ny = 0, nz = 1;
      if (r2 < 1) { nx = dx * 0.8; ny = dy * 0.8; nz = Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny)); }
      const o = 4 * (y * n + x);
      nm[o] = (nx * 0.5 + 0.5) * 255; nm[o + 1] = (ny * 0.5 + 0.5) * 255; nm[o + 2] = (nz * 0.5 + 0.5) * 255; nm[o + 3] = 255;
    }
    // Plan face à l'avant (+Y de GTA), UV DirectX : u vers la droite de l'écran, v vers le bas.
    const pos = new Float32Array([1, 0, 1, -1, 0, 1, -1, 0, -1, 1, 0, -1]);
    const nor = new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]);
    const uv = new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]);
    for (let i = 0; i < 4; i++) { const x = pos[3 * i], z = pos[3 * i + 2]; uv[2 * i] = (1 - x) / 2; uv[2 * i + 1] = (1 - z) / 2; }
    const d = {
      name: "dome", center: [0, 0, 0], radius: 1.5, bbMin: [-1, 0, -1], bbMax: [1, 0, 1], hasSkeleton: false,
      embeddedTextures: [
        { name: "dome_n", format: "A8B8G8R8", width: n, height: n, levels: 1, mips: [{ width: n, height: n, data: nm }] },
        { name: "gris", format: "A8B8G8R8", width: 4, height: 4, levels: 1, mips: [{ width: 4, height: 4, data: gray }] }],
      shaders: [{ name: "normal", file: "normal.sps", params: [
        { name: "DiffuseSampler", kind: "texture", texture: "gris" }, { name: "BumpSampler", kind: "texture", texture: "dome_n" },
        { name: "bumpiness", kind: "vector", values: [1, 0, 0, 0] }, { name: "specularFalloffMult", kind: "vector", values: [8, 0, 0, 0] }] }],
      lods: { high: [{ geometries: [{ vertexCount: 4, shaderIndex: 0, indices: new Uint16Array([0, 2, 1, 0, 3, 2]),
        attributes: { position: { array: pos, size: 3 }, normal: { array: nor, size: 3 }, uv0: { array: uv, size: 2 } } }] }],
        medium: [], low: [], veryLow: [] },
    };
    const m = window.__mcp;
    Object.assign(m.look, { metal: 0, reflections: 0.05 });
    m.addDrawable("dome", d);
    const measure = async () => {
      await new Promise((r) => setTimeout(r, 400));
      const c = document.querySelector("#view"), w = c.width, h = c.height;
      const t = document.createElement("canvas"); t.width = w; t.height = h;
      const ctx = t.getContext("2d"); ctx.drawImage(c, 0, 0);
      const patch = (fx, fy) => { const p = ctx.getImageData(Math.round(w * fx) - 6, Math.round(h * fy) - 6, 12, 12).data; let s = 0; for (let i = 0; i < p.length; i += 4) s += p[i] + p[i + 1] + p[i + 2]; return s / (p.length / 4) / 3; };
      const cy = 0.5, cx = 0.5, off = 0.11;
      return { haut: patch(cx, cy - off), bas: patch(cx, cy + off), gauche: patch(cx - off, cy), droite: patch(cx + off, cy) };
    };
    const normal = await measure();
    m.look.flipGreen = true; m.refreshMaterials();
    const flipped = await measure();
    m.look.flipGreen = false; m.refreshMaterials();
    return { normal, flipped };
  });
  await page.screenshot({ path: path.join(process.argv[3] || ".", "dome.png") });
  console.log(JSON.stringify(res), "erreurs:", errors.length ? errors : "aucune");
  await browser.close();
})();
