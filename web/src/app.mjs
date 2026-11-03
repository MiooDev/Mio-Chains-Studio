import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { readAsset, decodeTexture, ResourceError } from "./ydr_core.mjs";
import { makeZip } from "./zip.mjs";

const $ = (s, root = document) => root.querySelector(s);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

// ---------------------------------------------------------------------------------------------
// Décompression (DecompressionStream « deflate-raw » du navigateur)
// ---------------------------------------------------------------------------------------------

async function inflateRaw(bytes) {
  if (typeof DecompressionStream === "undefined") {
    throw new ResourceError("Ce navigateur ne sait pas décompresser les ressources : utilisez Chrome, Edge ou Firefox à jour.");
  }
  const ds = new DecompressionStream("deflate-raw");
  const writer = ds.writable.getWriter();
  writer.write(bytes).catch(() => {});
  writer.close().catch(() => {});
  const reader = ds.readable.getReader();
  const chunks = [];
  let total = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      chunks.push(value);
      total += value.length;
    }
  } catch (e) {
    if (!total) throw e;      // données en trop après la fin du flux : on garde ce qui a été lu
  }
  const out = new Uint8Array(total);
  let p = 0;
  for (const c of chunks) { out.set(c, p); p += c.length; }
  return out;
}

// ---------------------------------------------------------------------------------------------
// État
// ---------------------------------------------------------------------------------------------

const state = {
  chains: [],          // { id, name, file, drawable, group, example }
  ytds: [],            // { file, textures }
  messages: [],        // { kind: "error" | "info", text }
  current: null,
  shots: [],           // { name, blob, url }
  busy: false,
};
let nextId = 1;

const look = {
  style: "BIJOU", relief: 1, gloss: 1, reflections: 1.2, metal: 0.55, glow: 1, light: 1,
  flipGreen: false, background: "#26272b", transparent: false,
  view: "FACE", ratio: "1:1", size: 2048, margin: 1.12,
};
const STYLES = {
  BIJOU: { metal: 0.55, reflections: 1.2 },
  JEU: { metal: 0, reflections: 0.7 },
};

// ---------------------------------------------------------------------------------------------
// Scène three.js
// ---------------------------------------------------------------------------------------------

const canvas = $("#view");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1;
const gl = renderer.getContext();
const hasBptc = !!(gl.getExtension("EXT_texture_compression_bptc"));
const maxAniso = renderer.capabilities.getMaxAnisotropy();

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
const camera = new THREE.PerspectiveCamera(24, 1, 0.001, 100);
camera.position.set(0, 0, -1);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.12;

const key = new THREE.DirectionalLight(0xffffff, 2.2);
const rim = new THREE.DirectionalLight(0xdfe6ff, 1.4);
scene.add(key, rim);
const holder = new THREE.Group();
scene.add(holder);

function placeLights() {
  // Lumières attachées à la caméra : l'éclairage suit le point de vue (comme un studio photo).
  const dir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize();
  const right = new THREE.Vector3().crossVectors(camera.up, dir).normalize();
  const up = new THREE.Vector3().crossVectors(dir, right).normalize();
  const d = camera.position.distanceTo(controls.target) * 2 + 1;
  key.position.copy(controls.target).addScaledVector(dir, d).addScaledVector(right, -d * 0.6).addScaledVector(up, d * 0.8);
  rim.position.copy(controls.target).addScaledVector(dir, -d).addScaledVector(right, d * 0.7).addScaledVector(up, d * 0.3);
  key.target.position.copy(controls.target);
  rim.target.position.copy(controls.target);
  key.target.updateMatrixWorld();
  rim.target.updateMatrixWorld();
  key.intensity = 2.2 * look.light;
  rim.intensity = 1.4 * look.light;
}

function applyBackground() {
  if (look.transparent) {
    scene.background = null;
    renderer.setClearColor(0x000000, 0);
  } else {
    scene.background = new THREE.Color(look.background);
    renderer.setClearColor(look.background, 1);
  }
  $("#stage").classList.toggle("is-transparent", look.transparent);
}

// ---------------------------------------------------------------------------------------------
// Textures et matériaux
// ---------------------------------------------------------------------------------------------

const texCache = new Map();

function texturePool() {
  const pool = new Map();
  for (const y of state.ytds) for (const t of y.textures) if (!pool.has(t.name.toLowerCase())) pool.set(t.name.toLowerCase(), { tex: t, source: y.file });
  for (const c of state.chains) {
    if (!c.drawable) continue;
    for (const t of c.drawable.embeddedTextures) {
      const k = t.name.toLowerCase();
      if (!pool.has(k)) pool.set(k, { tex: t, source: c.file + " (intégrée)" });
    }
  }
  return pool;
}

function findTexture(drawable, name) {
  if (!name) return null;
  const k = name.toLowerCase();
  const own = drawable.embeddedTextures.find((t) => t.name.toLowerCase() === k);
  if (own) return { tex: own, source: "intégrée" };
  return texturePool().get(k) || null;
}

function threeTexture(t, color) {
  const keyName = `${t.name}|${t.format}|${t.width}x${t.height}|${color ? "c" : "n"}`;
  if (texCache.has(keyName)) return texCache.get(keyName);
  let tex = null;
  if (t.format === "BC7") {
    if (hasBptc && t.mips.length) {
      tex = new THREE.CompressedTexture(t.mips.map((m) => ({ data: m.data, width: m.width, height: m.height })),
        t.width, t.height, THREE.RGBA_BPTC_Format);
      tex.minFilter = t.mips.length > 1 ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter;
    }
  } else if (t.mips.length) {
    const m = t.mips[0];
    const rgba = decodeTexture(t.format, m.width, m.height, m.data);
    if (rgba) {
      tex = new THREE.DataTexture(new Uint8Array(rgba.buffer), m.width, m.height, THREE.RGBAFormat);
      tex.generateMipmaps = true;
      tex.minFilter = THREE.LinearMipmapLinearFilter;
    }
  }
  if (tex) {
    tex.flipY = false;           // les UV de GTA ont leur origine en haut à gauche
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.magFilter = THREE.LinearFilter;
    tex.anisotropy = maxAniso;
    tex.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    tex.needsUpdate = true;
  }
  texCache.set(keyName, tex);
  return tex;
}

const param = (shader, name) => shader.params.find((p) => p.name === name);
const vec = (shader, name, dflt) => { const p = param(shader, name); return p && p.values ? p.values[0] : dflt; };

/** État des textures d'un shader : [{ sampler, name, found, source, format }] */
function textureStatus(drawable, shader) {
  return shader.params.filter((p) => p.kind === "texture" && p.texture).map((p) => {
    const f = findTexture(drawable, p.texture);
    const usable = f && (f.tex.format !== "BC7" || hasBptc) && f.tex.mips.length > 0;
    return { sampler: p.name, name: p.texture, found: !!f, usable: !!usable, source: f ? f.source : "", format: f ? f.tex.format : "" };
  });
}

function glowPatch(mat) {
  mat.onBeforeCompile = (sh) => {
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nattribute float glow;\nvarying float vGlow;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvGlow = glow;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying float vGlow;")
      .replace("#include <emissivemap_fragment>", "#include <emissivemap_fragment>\ntotalEmissiveRadiance *= vGlow;");
  };
  mat.customProgramCacheKey = () => "mcp-glow";
}

function makeMaterial(drawable, shader) {
  const get = (sampler) => {
    const p = param(shader, sampler);
    if (!p || !p.texture) return null;
    const f = findTexture(drawable, p.texture);
    return f ? threeTexture(f.tex, sampler !== "BumpSampler") : null;
  };
  const mat = new THREE.MeshPhysicalMaterial({ color: 0xffffff, side: THREE.DoubleSide });
  const diffuse = get("DiffuseSampler");
  if (diffuse) mat.map = diffuse;
  else mat.color.set(0xb9bcc2);
  const bump = get("BumpSampler");
  if (bump) mat.normalMap = bump;
  const spec = get("SpecSampler");
  if (spec) mat.specularColorMap = spec;
  mat.specularIntensity = THREE.MathUtils.clamp(vec(shader, "specularIntensityMult", 1), 0, 1);
  const name = (shader.name + " " + shader.file).toLowerCase();
  const emissive = name.includes("emissive");
  if (emissive) {
    mat.emissive.set(0xffffff);
    if (diffuse) mat.emissiveMap = diffuse;
    glowPatch(mat);
  }
  if (name.includes("alpha") || name.includes("cutout") || name.includes("decal")) mat.alphaTest = 0.5;
  mat.userData.gta = {
    bumpiness: vec(shader, "bumpiness", 1),
    falloff: Math.max(1, vec(shader, "specularFalloffMult", 100)),
    emissive: emissive ? vec(shader, "emissiveMultiplier", 1) : 0,
  };
  applyLook(mat);
  return mat;
}

/** Réglages de l'interface appliqués à un matériau, sans le reconstruire. */
function applyLook(mat) {
  const g = mat.userData.gta;
  if (!g) return;
  const b = g.bumpiness * look.relief;
  mat.normalScale.set(b, look.flipGreen ? -b : b);
  // specularFalloffMult (exposant de type Phong) -> rugosité : r = (2 / (n + 2)) ^ 0.25
  mat.roughness = THREE.MathUtils.clamp(Math.pow(2 / (g.falloff + 2), 0.25) * look.gloss, 0.03, 1);
  mat.metalness = look.metal;
  mat.envMapIntensity = look.reflections;
  if (g.emissive) mat.emissiveIntensity = g.emissive * look.glow;
}

function modelsOf(drawable) {
  for (const lod of ["high", "medium", "low", "veryLow"]) if (drawable.lods[lod].length) return { lod, models: drawable.lods[lod] };
  return { lod: "", models: [] };
}

function buildGroup(chain) {
  const d = chain.drawable;
  const group = new THREE.Group();
  group.rotation.x = -Math.PI / 2;      // GTA : Z vers le haut -> three.js : Y vers le haut
  const mats = d.shaders.map((s) => makeMaterial(d, s));
  const fallback = new THREE.MeshPhysicalMaterial({ color: 0xb9bcc2, metalness: look.metal, roughness: 0.3 });
  for (const m of modelsOf(d).models) {
    for (const g of m.geometries) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(g.attributes.position.array, 3));
      if (g.attributes.normal) geo.setAttribute("normal", new THREE.BufferAttribute(g.attributes.normal.array, 3));
      if (g.attributes.uv0) geo.setAttribute("uv", new THREE.BufferAttribute(g.attributes.uv0.array, 2));
      const glow = new Float32Array(g.vertexCount);
      const c0 = g.attributes.colour0;
      if (c0 && c0.size === 4) for (let i = 0; i < g.vertexCount; i++) glow[i] = c0.array[4 * i + 2];
      geo.setAttribute("glow", new THREE.BufferAttribute(glow, 1));
      geo.setIndex(new THREE.BufferAttribute(g.indices, 1));
      if (!g.attributes.normal) geo.computeVertexNormals();
      group.add(new THREE.Mesh(geo, mats[g.shaderIndex] || fallback));
    }
  }
  return group;
}

function disposeGroup(group) {
  group.traverse((o) => {
    if (o.isMesh) {
      o.geometry.dispose();
      (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
    }
  });
}

// Chaîne d'exemple (affichée tant qu'aucun fichier n'est chargé)
function exampleGroup() {
  const group = new THREE.Group();
  const silver = new THREE.MeshPhysicalMaterial({ color: 0xdfe1e6, metalness: 1, roughness: 0.18 });
  const gold = new THREE.MeshPhysicalMaterial({ color: 0xd8b064, metalness: 1, roughness: 0.22 });
  const link = new THREE.TorusGeometry(0.011, 0.0034, 12, 28);
  link.scale(1, 0.72, 1);
  const n = 46;
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n * 2 - 1;
    pts.push(new THREE.Vector3(t * 0.11, 0.17 * t * t - 0.12, 0));      // collier en U, ouvert vers le haut
  }
  const curve = new THREE.CatmullRomCurve3(pts);
  const count = 34;
  for (let i = 0; i < count; i++) {
    const u = i / (count - 1);
    const p = curve.getPointAt(u), tan = curve.getTangentAt(u);
    const m = new THREE.Mesh(link, silver);
    m.position.copy(p);
    m.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), tan);
    if (i % 2) m.rotateX(Math.PI / 2);
    group.add(m);
  }
  const bottom = curve.getPointAt(0.5);
  const bail = new THREE.Mesh(new THREE.TorusGeometry(0.008, 0.0028, 12, 24), gold);
  bail.position.set(bottom.x, bottom.y - 0.012, 0);
  bail.rotation.y = Math.PI / 2;
  const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.034, 0.034, 0.006, 64), gold);
  disc.rotation.x = Math.PI / 2;
  disc.position.set(bottom.x, bottom.y - 0.052, 0);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.026, 0.0025, 12, 64), silver);
  ring.position.set(bottom.x, bottom.y - 0.052, -0.0035);
  group.add(bail, disc, ring);
  return group;
}

// ---------------------------------------------------------------------------------------------
// Cadrage et prises de vue
// ---------------------------------------------------------------------------------------------

const VIEWS = {
  FACE: { label: "Face", yaw: 0, pitch: 0 },
  TROIS_QUARTS: { label: "3/4", yaw: 35, pitch: 10 },
  PROFIL: { label: "Profil", yaw: 90, pitch: 0 },
  DESSUS: { label: "Dessus", yaw: 0, pitch: 65 },
  DOS: { label: "Dos", yaw: 180, pitch: 0 },
};
const RATIOS = { "1:1": 1, "4:5": 4 / 5, "16:9": 16 / 9 };

/** Cadre de la photo dans la vue (même proportion que l'image exportée). */
function photoFrame() {
  const sw = canvas.clientWidth || 1, sh = canvas.clientHeight || 1;
  const r = RATIOS[look.ratio];
  let bw = sw * 0.9, bh = bw / r;
  if (bh > sh * 0.9) { bh = sh * 0.9; bw = bh * r; }
  return { sw, sh, bw, bh, r };
}

function outputSize() {
  const r = RATIOS[look.ratio];
  return r >= 1 ? [look.size, Math.round(look.size / r)] : [Math.round(look.size * r), look.size];
}

function updateFrameOverlay() {
  const f = photoFrame();
  const box = $("#frame");
  box.style.width = `${f.bw}px`;
  box.style.height = `${f.bh}px`;
  const [w, h] = outputSize();
  $("#frame-label").textContent = `${w} × ${h} px`;
}

function photoFov() {
  const f = photoFrame();
  return 2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * f.bh / f.sh);
}

function frameCurrent(viewKey = look.view) {
  const obj = holder.children[0];
  if (!obj) return;
  const box = new THREE.Box3().setFromObject(obj);
  if (box.isEmpty()) return;
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const v = VIEWS[viewKey];
  const yaw = THREE.MathUtils.degToRad(v.yaw), pitch = THREE.MathUtils.degToRad(v.pitch);
  // Face = depuis l'avant du personnage (axe +Y de GTA, soit -Z ici).
  const dir = new THREE.Vector3(-Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch));
  const vf = photoFov(), hf = 2 * Math.atan(Math.tan(vf / 2) * RATIOS[look.ratio]);
  const dist = sphere.radius * look.margin / Math.sin(Math.min(vf, hf) / 2);
  controls.target.copy(sphere.center);
  camera.position.copy(sphere.center).addScaledVector(dir, dist);
  camera.near = Math.max(0.0005, dist / 200);
  camera.far = dist * 20;
  camera.updateProjectionMatrix();
  controls.update();
}

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  updateFrameOverlay();
}
new ResizeObserver(resize).observe(canvas);

let paused = false;
function loop() {
  requestAnimationFrame(loop);
  if (paused) return;
  controls.update();
  placeLights();
  renderer.render(scene, camera);
}

/** Rend la photo à la taille choisie, cadrée comme le cadre affiché. */
async function capture() {
  const [w, h] = outputSize();
  paused = true;
  const saved = { fov: camera.fov, aspect: camera.aspect };
  try {
    placeLights();
    camera.fov = THREE.MathUtils.radToDeg(photoFov());
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(1);
    renderer.setSize(w, h, false);
    renderer.render(scene, camera);
    const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
    if (!blob) throw new Error("La carte graphique n'a pas pu produire l'image (taille trop grande ?).");
    return { blob, w, h };
  } finally {
    camera.fov = saved.fov;
    resize();
    paused = false;
  }
}

// ---------------------------------------------------------------------------------------------
// Fichiers
// ---------------------------------------------------------------------------------------------

async function addFiles(files) {
  const list = [...files].filter((f) => /\.(ydr|ydd|ytd)$/i.test(f.name));
  const ignored = [...files].length - list.length;
  if (ignored) state.messages.push({ kind: "error", text: `${ignored} fichier(s) ignoré(s) : seuls les .ydr, .ydd et .ytd sont lus.` });
  // Les .ytd d'abord : leurs textures sont prêtes quand les chaînes s'affichent.
  list.sort((a, b) => (/\.ytd$/i.test(b.name) ? 1 : 0) - (/\.ytd$/i.test(a.name) ? 1 : 0));
  setBusy(true, "Lecture des fichiers…");
  let firstNew = null;
  for (const f of list) {
    try {
      const asset = await readAsset(f.name, new Uint8Array(await f.arrayBuffer()), inflateRaw);
      if (asset.kind === "ytd") {
        state.ytds = state.ytds.filter((y) => y.file !== f.name);
        state.ytds.push({ file: f.name, textures: asset.textures });
      } else {
        state.chains = state.chains.filter((c) => !c.example && c.file !== f.name);
        asset.drawables.forEach((d, i) => {
          const chain = { id: nextId++, name: asset.drawables.length > 1 ? d.name : asset.name, file: f.name, drawable: d, group: null };
          state.chains.push(chain);
          firstNew = firstNew || chain;
        });
      }
    } catch (e) {
      state.messages.push({ kind: "error", text: `${f.name} : ${e instanceof ResourceError ? e.message : "lecture impossible (" + e.message + ")."}` });
      if (!(e instanceof ResourceError)) console.error(e);
    }
  }
  // Nouvelles textures : les chaînes déjà construites sont refaites pour les utiliser.
  for (const c of state.chains) if (c.group && !c.example) { disposeGroup(c.group); c.group = null; }
  for (const t of texCache.values()) if (t) t.dispose();
  texCache.clear();
  setBusy(false);
  show(firstNew || state.current || state.chains[0], !!firstNew || !state.current);
  renderLists();
}

function groupOf(chain) {
  if (!chain.group) chain.group = chain.example ? exampleGroup() : buildGroup(chain);
  return chain.group;
}

function show(chain, reframe = true) {
  if (!chain) return;
  holder.clear();
  holder.add(groupOf(chain));
  state.current = chain;
  if (reframe) frameCurrent();
  renderLists();
}


// ---------------------------------------------------------------------------------------------
// Interface
// ---------------------------------------------------------------------------------------------

function setBusy(on, text = "") {
  state.busy = on;
  $("#busy").hidden = !on;
  $("#busy-text").textContent = text;
  for (const b of document.querySelectorAll("[data-needs-idle]")) b.disabled = on;
}

function stats(chain) {
  const d = chain.drawable;
  const { lod, models } = modelsOf(d);
  let v = 0, t = 0;
  for (const m of models) for (const g of m.geometries) { v += g.vertexCount; t += g.indices.length / 3; }
  return { lod, v, t };
}

const LOD_LABEL = { high: "High", medium: "Medium", low: "Low", veryLow: "Very Low" };
const SAMPLER_LABEL = { DiffuseSampler: "Couleur", BumpSampler: "Relief", SpecSampler: "Brillance" };

function renderLists() {
  const ul = $("#chains");
  ul.textContent = "";
  for (const c of state.chains) {
    const li = el("li", "chain" + (c === state.current ? " is-current" : ""));
    const btn = el("button", "chain-btn");
    btn.type = "button";
    btn.setAttribute("aria-pressed", String(c === state.current));
    btn.append(el("span", "chain-name", c.name));
    if (c.example) {
      btn.append(el("span", "chain-meta", "Exemple : déposez vos fichiers pour le remplacer"));
    } else {
      const s = stats(c);
      btn.append(el("span", "chain-meta", `${s.v.toLocaleString("fr-FR")} sommets · ${Math.round(s.t).toLocaleString("fr-FR")} triangles · LOD ${LOD_LABEL[s.lod] || "—"}`));
      const chips = el("span", "chips");
      const seen = new Set();
      for (const sh of c.drawable.shaders) {
        for (const st of textureStatus(c.drawable, sh)) {
          const k = st.sampler + st.name;
          if (seen.has(k)) continue;
          seen.add(k);
          const chip = el("span", "chip " + (st.usable ? "ok" : "missing"));
          chip.title = st.found ? `${st.name} · ${st.format} · ${st.source}` : `${st.name} : texture introuvable, ajoutez le .ytd qui la contient`;
          chip.append(el("span", "chip-mark", st.usable ? "✓" : "✕"), document.createTextNode(`${SAMPLER_LABEL[st.sampler] || st.sampler} · ${st.name}`));
          if (st.found && !st.usable) chip.title = `${st.name} : format ${st.format} non affichable par cette carte graphique`;
          chips.append(chip);
        }
      }
      if (chips.childNodes.length) btn.append(chips);
    }
    btn.addEventListener("click", () => show(c));
    li.append(btn);
    if (!c.example) {
      const rm = el("button", "icon-btn", "×");
      rm.type = "button";
      rm.title = `Retirer ${c.name}`;
      rm.setAttribute("aria-label", `Retirer ${c.name}`);
      rm.addEventListener("click", () => removeChain(c));
      li.append(rm);
    }
    ul.append(li);
  }
  const real = state.chains.filter((c) => !c.example);
  $("#count").textContent = real.length ? `${real.length} chaîne(s)` : "";
  const nTex = state.ytds.reduce((n, y) => n + y.textures.length, 0);
  $("#ytd-info").textContent = state.ytds.length
    ? `${state.ytds.length} .ytd · ${nTex} texture(s) : ${state.ytds.map((y) => y.file).join(", ")}`
    : "Aucun .ytd : seules les textures intégrées aux modèles sont utilisées.";
  const msgs = $("#messages");
  msgs.textContent = "";
  for (const m of state.messages.slice(-6)) msgs.append(el("li", "msg " + m.kind, m.text));
  $("#shoot-all").disabled = state.busy || !real.length;
  $("#empty-hint").hidden = real.length > 0;
}

function removeChain(c) {
  state.chains = state.chains.filter((x) => x !== c);
  if (c.group) disposeGroup(c.group);
  if (state.current === c) {
    state.current = null;
    holder.clear();
    if (!state.chains.length) addExample();
    else show(state.chains[0]);
  }
  renderLists();
}

function addExample() {
  const ex = { id: nextId++, name: "Chaîne d'exemple", file: "", drawable: null, group: null, example: true };
  state.chains.push(ex);
  show(ex);
}

function safeName(s) { return s.replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "") || "chaine"; }

function addShot(chain, blob, w, h) {
  const base = `${safeName(chain.name)}_${safeName(VIEWS[look.view].label)}`;
  let name = `${base}.png`, n = 2;
  while (state.shots.some((s) => s.name === name)) name = `${base}_${n++}.png`;
  const shot = { name, blob, url: URL.createObjectURL(blob), w, h };
  state.shots.push(shot);
  renderGallery();
  return shot;
}

function download(url, name) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
}

function renderGallery() {
  const g = $("#shots");
  g.textContent = "";
  for (const s of state.shots) {
    const fig = el("figure", "shot");
    const img = el("img");
    img.src = s.url;
    img.alt = s.name;
    img.loading = "lazy";
    const cap = el("figcaption");
    cap.append(el("span", "shot-name", s.name), el("span", "shot-size", `${s.w} × ${s.h}`));
    const actions = el("div", "shot-actions");
    const dl = el("button", "btn small", "Télécharger");
    dl.type = "button";
    dl.addEventListener("click", () => download(s.url, s.name));
    const rm = el("button", "icon-btn", "×");
    rm.type = "button";
    rm.title = `Supprimer ${s.name}`;
    rm.setAttribute("aria-label", `Supprimer ${s.name}`);
    rm.addEventListener("click", () => {
      URL.revokeObjectURL(s.url);
      state.shots = state.shots.filter((x) => x !== s);
      renderGallery();
    });
    actions.append(dl, rm);
    fig.append(img, cap, actions);
    g.append(fig);
  }
  $("#gallery-empty").hidden = state.shots.length > 0;
  $("#zip").disabled = !state.shots.length;
  $("#shots-count").textContent = state.shots.length ? `${state.shots.length} photo(s)` : "";
}

async function shootCurrent() {
  if (!state.current) return;
  setBusy(true, "Photo en cours…");
  try {
    const { blob, w, h } = await capture();
    addShot(state.current, blob, w, h);
  } catch (e) {
    state.messages.push({ kind: "error", text: e.message });
    renderLists();
  } finally {
    setBusy(false);
  }
}

async function shootAll() {
  const real = state.chains.filter((c) => !c.example);
  const back = state.current;
  for (let i = 0; i < real.length; i++) {
    setBusy(true, `Photo ${i + 1} / ${real.length} : ${real[i].name}`);
    show(real[i], true);
    await new Promise((r) => setTimeout(r, 30));
    try {
      const { blob, w, h } = await capture();
      addShot(real[i], blob, w, h);
    } catch (e) {
      state.messages.push({ kind: "error", text: `${real[i].name} : ${e.message}` });
    }
  }
  setBusy(false);
  if (back) show(back, false);
  renderLists();
}

async function zipAll() {
  setBusy(true, "Préparation du ZIP…");
  try {
    const files = [];
    for (const s of state.shots) files.push({ name: s.name, data: new Uint8Array(await s.blob.arrayBuffer()) });
    const blob = makeZip(files);
    const url = URL.createObjectURL(blob);
    download(url, "photos_chaines.zip");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } finally {
    setBusy(false);
  }
}

// Réglages -----------------------------------------------------------------------------------

function bindRange(id, prop, fmt, rebuild = true) {
  const input = $(`#${id}`), out = $(`#${id}-out`);
  const sync = () => { out.textContent = fmt(look[prop]); };
  input.value = look[prop];
  sync();
  input.addEventListener("input", () => {
    look[prop] = parseFloat(input.value);
    sync();
    if (rebuild) refreshMaterials();
  });
}

function refreshMaterials() {
  for (const c of state.chains) {
    if (!c.group || c.example) continue;
    c.group.traverse((o) => { if (o.isMesh) applyLook(o.material); });
  }
}

function initControls() {
  bindRange("relief", "relief", (v) => `× ${v.toFixed(2)}`);
  bindRange("gloss", "gloss", (v) => `× ${v.toFixed(2)}`);
  bindRange("reflections", "reflections", (v) => v.toFixed(2));
  bindRange("metal", "metal", (v) => v.toFixed(2));
  bindRange("glow", "glow", (v) => `× ${v.toFixed(2)}`);
  bindRange("light", "light", (v) => `× ${v.toFixed(2)}`, false);
  bindRange("margin", "margin", (v) => `${Math.round((1 / v) * 100)} %`, false);
  $("#margin").addEventListener("change", () => frameCurrent());

  for (const input of document.querySelectorAll('input[name="style"]')) {
    input.checked = input.value === look.style;
    input.addEventListener("change", () => {
      look.style = input.value;
      Object.assign(look, STYLES[look.style]);
      $("#metal").value = look.metal; $("#metal-out").textContent = look.metal.toFixed(2);
      $("#reflections").value = look.reflections; $("#reflections-out").textContent = look.reflections.toFixed(2);
      refreshMaterials();
    });
  }
  $("#flip-green").checked = look.flipGreen;
  $("#flip-green").addEventListener("change", (e) => { look.flipGreen = e.target.checked; refreshMaterials(); });
  $("#bg").value = look.background;
  $("#bg").addEventListener("input", (e) => { look.background = e.target.value; applyBackground(); });
  $("#transparent").checked = look.transparent;
  $("#transparent").addEventListener("change", (e) => { look.transparent = e.target.checked; applyBackground(); });

  const views = $("#views");
  for (const [k, v] of Object.entries(VIEWS)) {
    const b = el("button", "seg", v.label);
    b.type = "button";
    b.dataset.view = k;
    b.setAttribute("aria-pressed", String(k === look.view));
    b.addEventListener("click", () => {
      look.view = k;
      for (const x of views.children) x.setAttribute("aria-pressed", String(x.dataset.view === k));
      frameCurrent(k);
    });
    views.append(b);
  }
  $("#ratio").value = look.ratio;
  $("#ratio").addEventListener("change", (e) => { look.ratio = e.target.value; updateFrameOverlay(); frameCurrent(); });
  $("#size").value = String(look.size);
  $("#size").addEventListener("change", (e) => { look.size = parseInt(e.target.value, 10); updateFrameOverlay(); });
  $("#reframe").addEventListener("click", () => frameCurrent());
  $("#shoot").addEventListener("click", shootCurrent);
  $("#shoot-all").addEventListener("click", shootAll);
  $("#zip").addEventListener("click", zipAll);

  const input = $("#files");
  input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
  const drop = $("#drop");
  for (const t of [drop, document.body]) {
    t.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("is-over"); });
    t.addEventListener("dragleave", (e) => { if (e.target === drop || e.target === document.body) drop.classList.remove("is-over"); });
    t.addEventListener("drop", (e) => {
      e.preventDefault();
      drop.classList.remove("is-over");
      if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
    });
  }
}

initControls();
applyBackground();
resize();
addExample();
renderGallery();
renderLists();
loop();
if (!hasBptc) console.info("EXT_texture_compression_bptc absent : les textures BC7 ne pourront pas s'afficher.");

// Accès pour les tests automatisés
window.__mcp = {
  state, look, addFiles, shootCurrent, shootAll, frameCurrent, show, hasBptc, makeZip, refreshMaterials,
  addDrawable(name, drawable) {
    const c = { id: nextId++, name, file: name, drawable, group: null };
    state.chains = state.chains.filter((x) => !x.example);
    state.chains.push(c);
    show(c);
    renderLists();
  },
};
