import { readFileSync } from "fs";
import { inflateRawSync } from "zlib";
import { readAsset } from "../src/ydr_core.mjs";
const A = process.env.SOLLUMZ_ASSETS || "/root/.config/blender/5.2/extensions/user_default/sollumz/tests/assets";
const inflate = async (b) => new Uint8Array(inflateRawSync(b));
let ok = 0, bad = 0;
const check = (name, cond, detail = "") => { cond ? ok++ : bad++; console.log((cond ? "  OK  " : "  ÉCHEC ") + name + (cond ? "" : " " + detail)); };
for (const f of ["model_with_embedded_textures", "model_with_simple_bounds"]) {
  const xml = readFileSync(`${A}/cwxml/${f}.ydr.xml`, "utf8");
  const a = await readAsset(f + ".ydr", new Uint8Array(readFileSync(`${A}/gen8/${f}.ydr`)), inflate);
  const geoms = [...a.drawables[0].lods.high, ...a.drawables[0].lods.medium].flatMap(m => m.geometries);
  const vblocks = [...xml.matchAll(/<VertexBuffer>[\s\S]*?<Data>([\s\S]*?)<\/Data>/g)].map(m => m[1].trim().split(/\s+/).map(Number));
  const iblocks = [...xml.matchAll(/<IndexBuffer>\s*<Data>([\s\S]*?)<\/Data>/g)].map(m => m[1].trim().split(/\s+/).map(Number));
  check(`${f} : ${geoms.length} géométrie(s) comme le XML`, geoms.length === vblocks.length, `${geoms.length} vs ${vblocks.length}`);
  geoms.forEach((g, gi) => {
    const mine = [];
    for (let v = 0; v < g.vertexCount; v++) {
      for (const s of ["position", "normal", "colour0", "uv0"]) {
        const at = g.attributes[s]; const vals = Array.from(at.array.slice(v * at.size, v * at.size + at.size));
        mine.push(...(s === "colour0" ? vals.map(x => Math.round(x * 255)) : vals));
      }
    }
    const ref = vblocks[gi];
    const maxErr = Math.max(...ref.map((x, i) => Math.abs(x - mine[i])));
    check(`${f} géométrie ${gi} : ${ref.length} valeurs de sommets identiques (écart max ${maxErr.toExponential(1)})`, ref.length === mine.length && maxErr < 1e-5);
    check(`${f} géométrie ${gi} : indices identiques`, JSON.stringify(Array.from(g.indices)) === JSON.stringify(iblocks[gi]));
  });
}
for (const [f, dir] of [["gen8/model_with_embedded_textures.ydr", "model_with_embedded_textures"], ["gen8/txd.ytd", "txd"]]) {
  const a = await readAsset(f, new Uint8Array(readFileSync(`${A}/${f}`)), inflate);
  const t = a.textures ? a.textures[0] : a.drawables[0].embeddedTextures[0];
  const dds = readFileSync(`${A}/cwxml/${dir}/test_image.dds`);
  const payload = dds.subarray(128, 128 + t.mips[0].data.length);
  check(`${f} : pixels DXT5 identiques au .dds de référence (${payload.length} octets)`, Buffer.compare(Buffer.from(t.mips[0].data), payload) === 0);
}
console.log(`RÉSULTAT ${ok}/${ok + bad}`);
