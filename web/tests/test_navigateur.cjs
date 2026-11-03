const { chromium } = require("playwright");
const path = require("path"), fs = require("fs");
const A = process.env.SOLLUMZ_ASSETS || "/root/.config/blender/5.2/extensions/user_default/sollumz/tests/assets";
const OUT = process.argv[2];
(async () => {
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  const page = await browser.newPage({ viewport: { width: 1360, height: 860 }, acceptDownloads: true });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text()); });
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  await page.goto("file://" + path.resolve(process.argv[3]));
  await page.waitForFunction(() => window.__mcp && window.__mcp.state.chains.length === 1, null, { timeout: 20000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: OUT + "/1_exemple.png" });
  const r = {};
  r.bptc = await page.evaluate(() => window.__mcp.hasBptc);
  // Fichiers réels : ydr à texture externe + son ytd, ydr à texture intégrée, gen9 (refus attendu), fichier quelconque
  await page.setInputFiles("#files", [`${A}/gen8/model_with_simple_bounds.ydr`, `${A}/gen8/txd.ytd`,
    `${A}/gen8/model_with_embedded_textures.ydr`, `${A}/gen9/model_with_embedded_textures.ydr`]);
  await page.waitForFunction(() => window.__mcp.state.chains.length === 2 && !window.__mcp.state.busy, null, { timeout: 20000 });
  await page.waitForTimeout(600);
  r.chains = await page.evaluate(() => window.__mcp.state.chains.map(c => c.name));
  r.messages = await page.evaluate(() => window.__mcp.state.messages.map(m => m.text));
  r.chips = await page.evaluate(() => [...document.querySelectorAll(".chip")].map(c => c.className + " | " + c.textContent));
  r.meshes = await page.evaluate(() => { const c = window.__mcp.state.current; let n = 0, tex = []; c.group.traverse(o => { if (o.isMesh) { n++; tex.push(!!o.material.map, o.material.map && o.material.map.image.width); } }); return { name: c.name, n, tex }; });
  await page.screenshot({ path: OUT + "/2_charge.png" });
  // Photo, puis toutes les chaînes, puis ZIP
  await page.evaluate(() => window.__mcp.shootCurrent());
  await page.waitForFunction(() => window.__mcp.state.shots.length === 1 && !window.__mcp.state.busy, null, { timeout: 30000 });
  await page.evaluate(() => window.__mcp.shootAll());
  await page.waitForFunction(() => window.__mcp.state.shots.length === 3 && !window.__mcp.state.busy, null, { timeout: 60000 });
  r.shots = await page.evaluate(() => window.__mcp.state.shots.map(s => [s.name, s.w, s.h, s.blob.size]));
  const shotPng = await page.evaluate(async () => { const b = window.__mcp.state.shots[0].blob; const a = new Uint8Array(await b.arrayBuffer()); let s = ""; for (const x of a) s += String.fromCharCode(x); return btoa(s); });
  fs.writeFileSync(OUT + "/3_photo.png", Buffer.from(shotPng, "base64"));
  const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 20000 }), page.click("#zip")]);
  await dl.saveAs(OUT + "/photos.zip");
  r.zipName = dl.suggestedFilename();
  await page.screenshot({ path: OUT + "/4_planche.png" });
  // Largeur téléphone
  await page.setViewportSize({ width: 400, height: 860 });
  await page.waitForTimeout(400);
  r.phoneOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  await page.screenshot({ path: OUT + "/5_telephone.png", fullPage: false });
  r.errors = errors;
  console.log(JSON.stringify(r, null, 1));
  await browser.close();
})();
