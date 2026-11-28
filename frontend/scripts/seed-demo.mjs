// Local operator provisioning; Google authentication remains required by the app.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import path from "node:path";

const root = fileURLToPath(new URL("../../", import.meta.url));
const { values } = parseArgs({ options: {
  images: { type: "string", default: "20" },
  help: { type: "boolean", short: "h" },
} });
if (values.help) {
  console.log("Usage: npm run seed:demo -- --images <20|50|100|500> (default: 20)");
  process.exit(0);
}
if (!["20", "50", "100", "500"].includes(values.images))
  throw new Error("--images must be 20, 50, 100 or 500");
const config = JSON.parse(execFileSync("docker", ["compose", "config", "--format", "json"], {
  cwd: root, encoding: "utf8",
}));
if (config.name !== "mediamesh" || !config.services.keycloak.command.includes("start-dev"))
  throw new Error("Demo seeding requires the local development Compose stack");
execFileSync("docker", ["compose", "run", "--rm", "--no-deps", "-T",
  "-e", `ADMIN_EMAIL=${config.services.backend.environment.ADMIN_EMAIL}`,
  "-v", `${path.join(root, "ml-service/data/demo")}:/data/demo`,
  "-v", `${path.join(root, "ml-service/evaluation")}:/evaluation:ro`,
  "-v", `${path.join(root, "infra/demo")}:/demo-config:ro`,
  "ml-worker", "python", "-u", "-m", "mediamesh_ml.seed_demo", "--images", values.images,
], { cwd: root, stdio: "inherit" });
