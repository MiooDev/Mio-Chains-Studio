import { build } from "esbuild";
import { readFileSync, writeFileSync } from "fs";
const out = await build({ entryPoints: ["src/app.mjs"], bundle: true, minify: true, format: "iife", target: "es2020", write: false, legalComments: "eof" });
const js = out.outputFiles[0].text.replace(/<\/script/gi, "<\\/script");
const html = readFileSync("src/index.template.html", "utf8").replace("/*__APP__*/", () => js);
writeFileSync(process.argv[2], html);
console.log("écrit", process.argv[2], (html.length / 1024).toFixed(0), "Ko");
