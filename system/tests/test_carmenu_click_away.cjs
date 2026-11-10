// The console-strip context menu (#carmenu) closes on a click away, on window blur and on Escape.
const fs = require("fs"), assert = require("assert"), path = require("path");
const s = fs.readFileSync(path.join(__dirname, "..", "clients", "web", "index.html"), "utf8");
const i = s.indexOf('m.id = "carmenu"'), blk = s.slice(i, i + 3500);
for (const needle of ['addEventListener("mousedown", away, true)', 'addEventListener("blur", away)', 'ev.key === "Escape"', 'removeEventListener(t, away, t === "mousedown")'])
  assert(blk.includes(needle), "missing: " + needle);
console.log("ok carmenu click-away");
