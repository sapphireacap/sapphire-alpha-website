// Fails a production build if placeholder copy is still in the content
// file. Local builds set ALLOW_PENDING_COPY=1; Vercel builds do not, so a
// deploy carrying unapproved placeholder text cannot go out.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const file = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "src", "content", "homepage.js");
const hits = fs
  .readFileSync(file, "utf8")
  .split("\n")
  .map((line, i) => [i + 1, line])
  .filter(([, line]) => line.includes("[COPY PENDING]") && !line.trim().startsWith("//"));

if (hits.length && process.env.ALLOW_PENDING_COPY !== "1") {
  console.error(`\ncheck-copy: ${hits.length} placeholder string(s) in src/content/homepage.js still need approved copy:`);
  hits.forEach(([n, line]) => console.error(`  line ${n}: ${line.trim().slice(0, 100)}`));
  process.exit(1);
}
console.log(hits.length ? `check-copy: ${hits.length} placeholder(s) allowed (ALLOW_PENDING_COPY=1)` : "check-copy: ok");
