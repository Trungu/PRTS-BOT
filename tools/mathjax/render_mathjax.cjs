#!/usr/bin/env node
/* Render TeX from stdin to SVG file via MathJax. */
const fs = require("fs");
const path = require("path");

const { mathjax } = require("mathjax-full/js/mathjax.js");
const { TeX } = require("mathjax-full/js/input/tex.js");
const { SVG } = require("mathjax-full/js/output/svg.js");
const { liteAdaptor } = require("mathjax-full/js/adaptors/liteAdaptor.js");
const { RegisterHTMLHandler } = require("mathjax-full/js/handlers/html.js");
const { AllPackages } = require("mathjax-full/js/input/tex/AllPackages.js");

function parseArgs(argv) {
  const args = { out: "", color: "#CCCCCC", scale: "1.0", display: "true" };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--out" && i + 1 < argv.length) {
      args.out = argv[i + 1];
      i += 1;
    } else if (a === "--color" && i + 1 < argv.length) {
      args.color = argv[i + 1];
      i += 1;
    } else if (a === "--scale" && i + 1 < argv.length) {
      args.scale = argv[i + 1];
      i += 1;
    } else if (a === "--display" && i + 1 < argv.length) {
      args.display = argv[i + 1];
      i += 1;
    }
  }
  return args;
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.out) {
    throw new Error("Missing required --out argument");
  }

  const expr = (await readStdin()).trim();
  if (!expr) {
    throw new Error("Empty expression");
  }

  const adaptor = liteAdaptor();
  RegisterHTMLHandler(adaptor);
  const tex = new TeX({ packages: AllPackages });
  const svg = new SVG({
    fontCache: "none",
    scale: Math.max(0.1, Number.parseFloat(args.scale || "1.0") || 1.0),
  });

  const html = mathjax.document("", { InputJax: tex, OutputJax: svg });
  const display = String(args.display).toLowerCase() !== "false";
  const node = html.convert(expr, { display });
  const first = adaptor.firstChild(node);
  const svgNode = first || node;
  adaptor.setAttribute(svgNode, "style", `color: ${args.color};`);
  const svgText = adaptor.outerHTML(svgNode);

  const outPath = path.resolve(args.out);
  fs.writeFileSync(outPath, svgText, "utf8");
}

main().catch((err) => {
  const msg = err && err.message ? err.message : String(err);
  process.stderr.write(msg + "\n");
  process.exit(1);
});
