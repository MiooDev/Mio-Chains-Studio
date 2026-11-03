// Lecteur des ressources GTA V « Legacy » (gen8, RSC7) : YDR, YDD, YTD.
// Aucune dépendance : fonctionne dans le navigateur et dans Node (l'inflate est fourni par l'appelant).

export const FORMATS = {
  21: "A8R8G8B8", 22: "X8R8G8B8", 25: "A1R5G5B5", 28: "A8", 32: "A8B8G8R8", 50: "L8",
  0x31545844: "DXT1", 0x33545844: "DXT3", 0x35545844: "DXT5",
  0x31495441: "ATI1", 0x32495441: "ATI2", 0x20374342: "BC7",
};
const BLOCK_BYTES = { DXT1: 8, ATI1: 8, DXT3: 16, DXT5: 16, ATI2: 16, BC7: 16 };
const PIXEL_BYTES = { A8R8G8B8: 4, X8R8G8B8: 4, A8B8G8R8: 4, A1R5G5B5: 2, A8: 1, L8: 1 };

export const SEMANTICS = ["position", "blendWeights", "blendIndices", "normal", "colour0", "colour1",
  "uv0", "uv1", "uv2", "uv3", "uv4", "uv5", "uv6", "uv7", "tangent", "binormal"];
// Types des composants (VertexComponentType) et leur taille en octets.
const TYPE_SIZE = [0, 4, 4, 8, 4, 8, 12, 16, 4, 4, 4, 0, 0, 0, 0, 0];

export function joaat(text) {
  let h = 0;
  const s = text.toLowerCase();
  for (let i = 0; i < s.length; i++) {
    h = (h + s.charCodeAt(i)) >>> 0;
    h = (h + (h << 10)) >>> 0;
    h = (h ^ (h >>> 6)) >>> 0;
  }
  h = (h + (h << 3)) >>> 0;
  h = (h ^ (h >>> 11)) >>> 0;
  h = (h + (h << 15)) >>> 0;
  return h >>> 0;
}

const KNOWN = ["DiffuseSampler", "BumpSampler", "SpecSampler", "DetailSampler", "TextureSamplerDiffPal",
  "DiffuseSampler2", "BumpSampler2", "SpecSampler2", "EnvironmentSampler", "VolumeSampler", "TintPaletteSampler",
  "bumpiness", "specularIntensityMult", "specularFalloffMult", "specularFresnel", "emissiveMultiplier",
  "matMaterialColorScale", "HardAlphaBlend", "useTessellation", "wetnessMultiplier", "globalAnimUV0", "globalAnimUV1",
  "umGlobalParams", "envEffFatThickness", "detailSettings", "StubbleControl", "specMapIntMask", "AlphaTestValue"];
const SHADERS = ["default", "ped", "ped_emissive", "ped_alpha", "ped_decal", "ped_default", "ped_hair_spiked",
  "spec", "normal", "normal_spec", "normal_spec_alpha", "emissive", "emissivestrong", "normal_spec_emissive",
  "cutout", "default_noedge", "trees", "glass", "vehicle_paint1", "vehicle_mesh", "ped_fur", "ped_cloth",
  "ped_cloth_enveff", "ped_enveff", "ped_default_enveff", "ped_default_mp", "ped_default_palette", "ped_palette",
  "ped_nopeddamagedecals", "ped_wrinkle", "ped_wrinkle_cs", "normal_spec_detail", "spec_const", "decal",
  "normal_decal", "alpha", "emissive_alpha", "normal_alpha", "spec_alpha", "ped_decal_decoration", "ped_hair_cutout_alpha"];
const NAME_OF = new Map();
for (const n of KNOWN) NAME_OF.set(joaat(n), n);
for (const n of SHADERS) { NAME_OF.set(joaat(n), n); NAME_OF.set(joaat(n + ".sps"), n + ".sps"); }
export const nameOfHash = (h) => NAME_OF.get(h) || `0x${h.toString(16).padStart(8, "0")}`;

function pageSize(flags) {
  const n = ((flags >>> 27) & 1) + (((flags >>> 26) & 1) << 1) + (((flags >>> 25) & 1) << 2) + (((flags >>> 24) & 1) << 3)
    + (((flags >>> 17) & 0x7f) << 4) + (((flags >>> 11) & 0x3f) << 5) + (((flags >>> 7) & 0xf) << 6)
    + (((flags >>> 5) & 0x3) << 7) + (((flags >>> 4) & 1) << 8);
  return (0x200 << (flags & 0xf)) * n;
}

export class ResourceError extends Error {}

/** Lit l'en-tête RSC7 et décompresse. `inflateRaw(Uint8Array) -> Promise<Uint8Array>` */
export async function openResource(bytes, inflateRaw) {
  if (bytes.length < 16) throw new ResourceError("Fichier trop court : ce n'est pas une ressource GTA V.");
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const magic = dv.getUint32(0, true);
  if (magic === 0x38435352) throw new ResourceError("Ressource RSC8 : format non pris en charge.");
  if (magic !== 0x37435352) {
    throw new ResourceError("En-tête RSC7 absent : le fichier est chiffré (fichier de jeu non extrait) ou ce n'est "
      + "pas un .ydr / .ydd / .ytd. Exportez-le depuis OpenIV ou CodeWalker.");
  }
  const version = dv.getUint32(4, true), sysFlags = dv.getUint32(8, true), gfxFlags = dv.getUint32(12, true);
  const sysSize = pageSize(sysFlags), gfxSize = pageSize(gfxFlags);
  let data;
  try {
    data = await inflateRaw(bytes.subarray(16));
  } catch (e) {
    throw new ResourceError("Décompression impossible : fichier abîmé ou chiffré.");
  }
  if (data.length < sysSize + gfxSize) throw new ResourceError("Données plus courtes que prévu : fichier tronqué ou abîmé.");
  return new Resource(data, version, sysSize, gfxSize);
}

export class Resource {
  constructor(data, version, sysSize, gfxSize) {
    this.data = data;
    this.dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
    this.version = version;
    this.sysSize = sysSize;
    this.gfxSize = gfxSize;
  }
  off(ptr) {
    if (!ptr) return -1;
    const base = ptr >>> 28, o = ptr & 0x0fffffff;
    let r;
    if (base === 5) r = o;
    else if (base === 6) r = this.sysSize + o;
    else throw new ResourceError(`Pointeur invalide 0x${ptr.toString(16)}.`);
    if (r >= this.data.length) throw new ResourceError(`Pointeur hors du fichier 0x${ptr.toString(16)}.`);
    return r;
  }
  u8(o) { return this.dv.getUint8(o); }
  u16(o) { return this.dv.getUint16(o, true); }
  u32(o) { return this.dv.getUint32(o, true); }
  f32(o) { return this.dv.getFloat32(o, true); }
  /** Pointeur 64 bits : seuls les 32 bits bas sont utiles (les 32 bits hauts valent 0). */
  ptr(o) { return this.dv.getUint32(o, true); }
  at(o) { return this.off(this.ptr(o)); }
  vec3(o) { return [this.f32(o), this.f32(o + 4), this.f32(o + 8)]; }
  cstr(o) {
    if (o < 0) return "";
    let e = o;
    while (e < this.data.length && this.data[e] !== 0) e++;
    return new TextDecoder("latin1").decode(this.data.subarray(o, e));
  }
  /** ResourcePointerList64 : { ulong pointeur ; ushort nombre ; ushort capacité } -> offsets des éléments */
  pointerList(o) {
    const list = this.at(o), count = this.u16(o + 8);
    const out = [];
    if (list < 0) return out;
    for (let i = 0; i < count; i++) {
      const item = this.at(list + 8 * i);
      if (item >= 0) out.push(item);
    }
    return out;
  }
}

// ---------------------------------------------------------------------------------------------
// Textures
// ---------------------------------------------------------------------------------------------

export function textureByteSize(format, w, h) {
  if (BLOCK_BYTES[format]) return Math.max(1, Math.ceil(w / 4)) * Math.max(1, Math.ceil(h / 4)) * BLOCK_BYTES[format];
  if (PIXEL_BYTES[format]) return w * h * PIXEL_BYTES[format];
  return 0;
}

export function readTexture(res, o) {
  const name = res.cstr(res.at(o + 0x28));
  const width = res.u16(o + 0x50), height = res.u16(o + 0x52), depth = res.u16(o + 0x54);
  const stride = res.u16(o + 0x56), fourcc = res.u32(o + 0x58), levels = res.u8(o + 0x5d);
  const format = FORMATS[fourcc] || `inconnu (${fourcc})`;
  const dataOff = res.at(o + 0x70);
  const mips = [];
  if (dataOff >= 0 && (BLOCK_BYTES[format] || PIXEL_BYTES[format])) {
    let p = dataOff, w = width, h = height;
    for (let i = 0; i < Math.max(1, levels); i++) {
      const size = textureByteSize(format, w, h);
      if (p + size > res.data.length) break;
      mips.push({ width: w, height: h, data: res.data.subarray(p, p + size) });
      p += size;
      w = Math.max(1, w >> 1);
      h = Math.max(1, h >> 1);
    }
  }
  return { name, width, height, depth, stride, format, levels, mips };
}

export function readTextureDictionary(res, o) {
  const textures = res.pointerList(o + 0x30).map((t) => readTexture(res, t));
  return { textures };
}

// ---------------------------------------------------------------------------------------------
// Shaders
// ---------------------------------------------------------------------------------------------

function readShader(res, s) {
  const paramsOff = res.at(s + 0x00);
  const nameHash = res.u32(s + 0x08), count = res.u8(s + 0x10), bucket = res.u8(s + 0x11);
  const fileHash = res.u32(s + 0x18);
  const params = [];
  if (paramsOff >= 0) {
    let dataSize = 0;
    const raw = [];
    for (let i = 0; i < count; i++) {
      const e = paramsOff + 16 * i;
      const type = res.u8(e), ptr = res.ptr(e + 8);
      raw.push({ type, ptr });
      if (type > 0) dataSize += 16 * type;
    }
    const hashesOff = paramsOff + 16 * count + dataSize;
    raw.forEach((p, i) => {
      const hash = res.u32(hashesOff + 4 * i);
      const name = nameOfHash(hash);
      if (p.type === 0) {
        const t = res.off(p.ptr);
        params.push({ name, hash, kind: "texture", texture: t >= 0 ? res.cstr(res.at(t + 0x28)) : "" });
      } else {
        const v = res.off(p.ptr);
        const values = [];
        for (let k = 0; k < 4 * p.type && v >= 0; k++) values.push(res.f32(v + 4 * k));
        params.push({ name, hash, kind: p.type === 1 ? "vector" : "array", values });
      }
    });
  }
  return { name: nameOfHash(nameHash), file: nameOfHash(fileHash), bucket, params };
}

function readShaderGroup(res, o) {
  const texDict = res.at(o + 0x08);
  const shaders = res.pointerList(o + 0x10).map((s) => readShader(res, s));
  return { shaders, textures: texDict >= 0 ? readTextureDictionary(res, texDict).textures : [] };
}

// ---------------------------------------------------------------------------------------------
// Géométrie
// ---------------------------------------------------------------------------------------------

function half(u) {
  const s = (u & 0x8000) ? -1 : 1, e = (u >> 10) & 0x1f, f = u & 0x3ff;
  if (e === 0) return s * Math.pow(2, -14) * (f / 1024);
  if (e === 31) return f ? NaN : s * Infinity;
  return s * Math.pow(2, e - 15) * (1 + f / 1024);
}

function readComponent(dv, o, type, out, k) {
  switch (type) {
    case 1: out[k] = half(dv.getUint16(o, true)); out[k + 1] = half(dv.getUint16(o + 2, true)); return 2;
    case 2: out[k] = dv.getFloat32(o, true); return 1;
    case 3: for (let i = 0; i < 4; i++) out[k + i] = half(dv.getUint16(o + 2 * i, true)); return 4;
    case 5: out[k] = dv.getFloat32(o, true); out[k + 1] = dv.getFloat32(o + 4, true); return 2;
    case 6: for (let i = 0; i < 3; i++) out[k + i] = dv.getFloat32(o + 4 * i, true); return 3;
    case 7: for (let i = 0; i < 4; i++) out[k + i] = dv.getFloat32(o + 4 * i, true); return 4;
    case 8: for (let i = 0; i < 4; i++) out[k + i] = dv.getUint8(o + i); return 4;
    case 9: for (let i = 0; i < 4; i++) out[k + i] = dv.getUint8(o + i) / 255; return 4;
    case 10: { // Dec3N : 3 × 10 bits signés
      const v = dv.getUint32(o, true);
      for (let i = 0; i < 3; i++) {
        let c = (v >> (10 * i)) & 0x3ff;
        if (c & 0x200) c -= 0x400;
        out[k + i] = Math.max(-1, c / 511);
      }
      return 3;
    }
    default: return 0;
  }
}
const COMPONENTS = [0, 2, 1, 4, 1, 2, 3, 4, 4, 4, 3, 0, 0, 0, 0, 0];

function readGeometry(res, g) {
  const vb = res.at(g + 0x18), ib = res.at(g + 0x38);
  if (vb < 0 || ib < 0) throw new ResourceError("Géométrie sans tampon de sommets ou d'indices.");
  const stride = res.u16(vb + 0x08), vcount = res.u32(vb + 0x18);
  let vdata = res.at(vb + 0x10);
  if (vdata < 0) vdata = res.at(vb + 0x20);
  const decl = res.at(vb + 0x30);
  const flags = res.u32(decl), declStride = res.u16(decl + 4);
  const typesLo = res.u32(decl + 8), typesHi = res.u32(decl + 12);
  const layout = [];
  let offset = 0;
  for (let i = 0; i < 16; i++) {
    if (!(flags & (1 << i))) continue;
    const type = i < 8 ? (typesLo >>> (4 * i)) & 0xf : (typesHi >>> (4 * (i - 8))) & 0xf;
    layout.push({ semantic: SEMANTICS[i], type, offset });
    offset += TYPE_SIZE[type];
  }
  if (offset !== stride || declStride !== stride) {
    throw new ResourceError(`Format de sommets inattendu (taille ${offset} au lieu de ${stride}).`);
  }
  const dv = new DataView(res.data.buffer, res.data.byteOffset + vdata, vcount * stride);
  const attributes = {};
  for (const c of layout) {
    const n = COMPONENTS[c.type];
    if (!n) continue;
    const arr = new Float32Array(vcount * n);
    for (let v = 0; v < vcount; v++) readComponent(dv, v * stride + c.offset, c.type, arr, v * n);
    attributes[c.semantic] = { array: arr, size: n, type: c.type };
  }
  const icount = res.u32(ib + 0x08), idata = res.at(ib + 0x10);
  const indices = new Uint16Array(icount);
  for (let i = 0; i < icount; i++) indices[i] = res.u16(idata + 2 * i);
  return { vertexCount: vcount, stride, layout, attributes, indices };
}

function readModel(res, m) {
  const geomsList = res.at(m + 0x08), count = res.u16(m + 0x10), mapping = res.at(m + 0x20);
  const geometries = [];
  for (let i = 0; i < count; i++) {
    const g = res.at(geomsList + 8 * i);
    const geo = readGeometry(res, g);
    geo.shaderIndex = mapping >= 0 ? res.u16(mapping + 2 * i) : 0;
    geometries.push(geo);
  }
  return { geometries, skeletonBinding: res.u32(m + 0x28) };
}

const LODS = [["high", 0x50], ["medium", 0x58], ["low", 0x60], ["veryLow", 0x68]];

export function readDrawable(res, o, fallbackName = "") {
  const sg = res.at(o + 0x10);
  const shaderGroup = sg >= 0 ? readShaderGroup(res, sg) : { shaders: [], textures: [] };
  const lods = {};
  for (const [lod, field] of LODS) {
    const list = res.at(o + field);
    lods[lod] = list >= 0 ? res.pointerList(list).map((m) => readModel(res, m)) : [];
  }
  let name = "";
  try { name = res.cstr(res.at(o + 0xa8)); } catch (e) { name = ""; }
  return {
    name: name || fallbackName,
    center: res.vec3(o + 0x20), radius: res.f32(o + 0x2c),
    bbMin: res.vec3(o + 0x30), bbMax: res.vec3(o + 0x40),
    hasSkeleton: res.ptr(o + 0x18) !== 0,
    shaders: shaderGroup.shaders, embeddedTextures: shaderGroup.textures, lods,
  };
}

export function readDrawableDictionary(res) {
  const hashesOff = res.at(0x20), count = res.u16(0x28);
  const drawables = res.pointerList(0x30);
  return drawables.map((d, i) => readDrawable(res, d, hashesOff >= 0 ? nameOfHash(res.u32(hashesOff + 4 * i)) : `drawable_${i}`));
}

/** Lit un fichier .ydr / .ydd / .ytd (gen8). */
export async function readAsset(fileName, bytes, inflateRaw) {
  const lower = fileName.toLowerCase();
  const kind = lower.endsWith(".ytd") ? "ytd" : lower.endsWith(".ydd") ? "ydd" : lower.endsWith(".ydr") ? "ydr" : null;
  if (!kind) throw new ResourceError("Extension non prise en charge : choisissez des .ydr, .ydd ou .ytd.");
  const res = await openResource(bytes, inflateRaw);
  const expected = { ydr: 165, ydd: 165, ytd: 13 }[kind];
  const gen9 = { ydr: 159, ydd: 159, ytd: 5 }[kind];
  if (res.version === gen9) {
    throw new ResourceError("Fichier « Enhanced » (gen9, version " + res.version + ") : seuls les fichiers Legacy "
      + "(FiveM, version " + expected + ") sont pris en charge.");
  }
  if (res.version !== expected) {
    throw new ResourceError(`Version de ressource ${res.version} inattendue pour un .${kind} (attendu : ${expected}).`);
  }
  const base = fileName.replace(/^.*[\\/]/, "").replace(/\.(ydr|ydd|ytd)$/i, "");
  if (kind === "ytd") return { kind, name: base, textures: readTextureDictionary(res, 0).textures };
  if (kind === "ydd") return { kind, name: base, drawables: readDrawableDictionary(res) };
  return { kind, name: base, drawables: [readDrawable(res, 0, base)] };
}

// ---------------------------------------------------------------------------------------------
// Décodage des textures en RGBA 8 bits (origine en haut à gauche, comme DirectX)
// ---------------------------------------------------------------------------------------------

function rgb565(c, out) {
  out[0] = ((c >> 11) & 31) * 255 / 31;
  out[1] = ((c >> 5) & 63) * 255 / 63;
  out[2] = (c & 31) * 255 / 31;
}

function colorBlock(src, o, dst, w, h, bx, by, alphaMode, alphaOut) {
  const c0 = src[o] | (src[o + 1] << 8), c1 = src[o + 2] | (src[o + 3] << 8);
  const p = [[0, 0, 0, 255], [0, 0, 0, 255], [0, 0, 0, 255], [0, 0, 0, 255]];
  rgb565(c0, p[0]); rgb565(c1, p[1]);
  if (!alphaMode || c0 > c1) {
    for (let k = 0; k < 3; k++) { p[2][k] = (2 * p[0][k] + p[1][k]) / 3; p[3][k] = (p[0][k] + 2 * p[1][k]) / 3; }
  } else {
    for (let k = 0; k < 3; k++) { p[2][k] = (p[0][k] + p[1][k]) / 2; p[3][k] = 0; }
    p[3][3] = 0;
  }
  const bits = src[o + 4] | (src[o + 5] << 8) | (src[o + 6] << 16) | (src[o + 7] << 24);
  for (let i = 0; i < 16; i++) {
    const x = bx * 4 + (i & 3), y = by * 4 + (i >> 2);
    if (x >= w || y >= h) continue;
    const c = p[(bits >>> (2 * i)) & 3], d = (y * w + x) * 4;
    dst[d] = c[0] + 0.5; dst[d + 1] = c[1] + 0.5; dst[d + 2] = c[2] + 0.5;
    dst[d + 3] = alphaOut ? alphaOut[i] : c[3];
  }
}

function alphaBlock(src, o, out) {
  const a0 = src[o], a1 = src[o + 1];
  const a = [a0, a1, 0, 0, 0, 0, 0, 0];
  if (a0 > a1) for (let i = 1; i < 7; i++) a[i + 1] = ((7 - i) * a0 + i * a1) / 7;
  else { for (let i = 1; i < 5; i++) a[i + 1] = ((5 - i) * a0 + i * a1) / 5; a[6] = 0; a[7] = 255; }
  let lo = src[o + 2] | (src[o + 3] << 8) | (src[o + 4] << 16), hi = src[o + 5] | (src[o + 6] << 8) | (src[o + 7] << 16);
  for (let i = 0; i < 16; i++) {
    const idx = i < 8 ? (lo >> (3 * i)) & 7 : (hi >> (3 * (i - 8))) & 7;
    out[i] = Math.round(a[idx]);
  }
  return out;
}

export function decodeTexture(format, width, height, data) {
  const out = new Uint8ClampedArray(width * height * 4);
  const bw = Math.max(1, Math.ceil(width / 4)), bh = Math.max(1, Math.ceil(height / 4));
  const tmp = new Array(16), tmp2 = new Array(16);
  const px = (x, y) => (y * width + x) * 4;
  switch (format) {
    case "DXT1":
      for (let by = 0; by < bh; by++) for (let bx = 0; bx < bw; bx++) colorBlock(data, (by * bw + bx) * 8, out, width, height, bx, by, true, null);
      return out;
    case "DXT3":
      for (let by = 0; by < bh; by++) for (let bx = 0; bx < bw; bx++) {
        const o = (by * bw + bx) * 16;
        for (let i = 0; i < 16; i++) tmp[i] = ((data[o + (i >> 1)] >> (4 * (i & 1))) & 15) * 17;
        colorBlock(data, o + 8, out, width, height, bx, by, false, tmp);
      }
      return out;
    case "DXT5":
      for (let by = 0; by < bh; by++) for (let bx = 0; bx < bw; bx++) {
        const o = (by * bw + bx) * 16;
        colorBlock(data, o + 8, out, width, height, bx, by, false, alphaBlock(data, o, tmp));
      }
      return out;
    case "ATI1": case "ATI2":
      for (let by = 0; by < bh; by++) for (let bx = 0; bx < bw; bx++) {
        const o = (by * bw + bx) * (format === "ATI1" ? 8 : 16);
        alphaBlock(data, o, tmp);
        if (format === "ATI2") alphaBlock(data, o + 8, tmp2);
        for (let i = 0; i < 16; i++) {
          const x = bx * 4 + (i & 3), y = by * 4 + (i >> 2);
          if (x >= width || y >= height) continue;
          const d = px(x, y);
          if (format === "ATI1") { out[d] = out[d + 1] = out[d + 2] = tmp[i]; out[d + 3] = 255; continue; }
          // Normal map à 2 canaux : Z reconstruit.
          const nx = tmp[i] / 127.5 - 1, ny = tmp2[i] / 127.5 - 1;
          const nz = Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny));
          out[d] = tmp[i]; out[d + 1] = tmp2[i]; out[d + 2] = (nz * 0.5 + 0.5) * 255; out[d + 3] = 255;
        }
      }
      return out;
    case "A8R8G8B8": case "X8R8G8B8":
      for (let i = 0; i < width * height; i++) {
        out[4 * i] = data[4 * i + 2]; out[4 * i + 1] = data[4 * i + 1]; out[4 * i + 2] = data[4 * i];
        out[4 * i + 3] = format === "X8R8G8B8" ? 255 : data[4 * i + 3];
      }
      return out;
    case "A8B8G8R8":
      out.set(data.subarray(0, width * height * 4));
      return out;
    case "A1R5G5B5":
      for (let i = 0; i < width * height; i++) {
        const c = data[2 * i] | (data[2 * i + 1] << 8);
        out[4 * i] = ((c >> 10) & 31) * 255 / 31; out[4 * i + 1] = ((c >> 5) & 31) * 255 / 31;
        out[4 * i + 2] = (c & 31) * 255 / 31; out[4 * i + 3] = c & 0x8000 ? 255 : 0;
      }
      return out;
    case "L8": case "A8":
      for (let i = 0; i < width * height; i++) {
        const v = data[i];
        if (format === "L8") { out[4 * i] = out[4 * i + 1] = out[4 * i + 2] = v; out[4 * i + 3] = 255; }
        else { out[4 * i] = out[4 * i + 1] = out[4 * i + 2] = 255; out[4 * i + 3] = v; }
      }
      return out;
    default:
      return null;      // BC7 : décodé par la carte graphique si elle le permet
  }
}
