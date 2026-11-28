import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from prepare import ROOT, prepare


class DeploymentTests(unittest.TestCase):
    def test_fresh_identity_scoped_storage_and_private_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime"
            prepare(
                "archive.mediamesh-demo.org",
                "ops@mediamesh-demo.org",
                "mediameshsmoketest",
                "owner@mediamesh-demo.org",
                "mediamesh",
                output,
            )
            env = dict(
                line.split("=", 1)
                for line in (output / "deploy.env").read_text().splitlines()
            )
            realm = json.loads((output / "realm/mediamesh-realm.json").read_text())
            people = [u for u in realm["users"] if not u.get("serviceAccountClientId")]
            self.assertEqual(people, [])
            self.assertNotIn("BOOTSTRAP_ADMIN_SUBJECT", env)
            self.assertEqual(env["ADMIN_EMAIL"], "owner@mediamesh-demo.org")
            self.assertIn("owner@mediamesh-demo.org", (output / "first-login.txt").read_text())
            self.assertIn("GOOGLE_CLIENT_ID", env)
            self.assertEqual(realm["identityProviders"][0]["alias"], "google")
            [service] = [u for u in realm["users"] if u.get("serviceAccountClientId")]
            self.assertEqual(service["clientRoles"], {"realm-management": ["manage-users"]})
            [provisioner] = [c for c in realm["clients"] if c["clientId"] == "mediamesh-provisioner"]
            self.assertEqual(provisioner["secret"], env["KEYCLOAK_PROVISIONER_SECRET"])
            self.assertNotIn("local-provisioner-only", json.dumps(realm))
            self.assertFalse(realm["clients"][0]["directAccessGrantsEnabled"])
            self.assertEqual(
                realm["clients"][0]["webOrigins"],
                ["https://archive.mediamesh-demo.org"],
            )
            self.assertNotIn("local-demo-only", json.dumps(realm))
            self.assertEqual((output / "deploy.env").stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output / "realm").stat().st_mode & 0o777, 0o755)
            self.assertNotIn("AWS_ACCESS_KEY_ID", env)
            self.assertEqual(env["AZURE_STORAGE_ACCOUNT"], "mediameshsmoketest")
            self.assertEqual(env["AZURE_STORAGE_CONTAINER"], "mediamesh")
            original = (output / "deploy.env").read_bytes()
            with self.assertRaises(ValueError):
                prepare(
                    "archive.mediamesh-demo.org",
                    "ops@mediamesh-demo.org",
                    "mediameshsmoketest",
                    "owner@mediamesh-demo.org",
                    "mediamesh",
                    output,
                )
            self.assertEqual(original, (output / "deploy.env").read_bytes())

    def test_invalid_inputs_write_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            for domain in [
                "localhost",
                "https://archive.org",
                "foo.org/path",
                "example.com",
                "bad\nHOST=oops.org",
            ]:
                output = Path(directory) / "runtime"
                with self.assertRaises(ValueError):
                    prepare(
                        domain,
                        "ops@site.org",
                        "private-bucket",
                        "owner@site.org",
                        "mediamesh",
                        output,
                    )
                self.assertFalse(output.exists())

    @unittest.skipUnless(
        shutil.which("docker"),
        "Docker Compose is required for deployment config validation",
    )
    def test_composed_release_has_no_demo_storage_credentials_or_public_internal_services(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime"
            prepare(
                "archive.mediamesh-demo.org",
                "ops@mediamesh-demo.org",
                "mediameshsmoketest",
                "owner@mediamesh-demo.org",
                "mediamesh",
                output,
            )
            # Shell variables override --env-file in Compose; CI exports ADMIN_EMAIL.
            defined = {
                line.split("=", 1)[0]
                for line in (output / "deploy.env").read_text().splitlines()
                if "=" in line and not line.lstrip().startswith("#")
            }
            environment = {k: v for k, v in os.environ.items() if k not in defined}
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    str(output / "deploy.env"),
                    "-f",
                    str(ROOT / "compose.deploy.yaml"),
                    "config",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
                env=environment,
            )
            config = json.loads(result.stdout)
            self.assertEqual(config["name"], "mediamesh-deploy")
            self.assertEqual(
                config["services"]["backend"]["environment"]["ADMIN_EMAIL"],
                "owner@mediamesh-demo.org",
            )
            services = config["services"]
            self.assertNotIn("s3", services)
            self.assertEqual(
                services["keycloak"]["command"], ["start", "--import-realm"]
            )
            self.assertEqual(services["keycloak"]["environment"]["KC_DB"], "postgres")
            for name, service in services.items():
                if name not in {"edge", "prometheus"}:
                    self.assertFalse(service.get("ports"), name)
                for key in [
                    "AWS_ACCESS_KEY_ID",
                    "AWS_SECRET_ACCESS_KEY",
                    "S3_ENDPOINT",
                    "ML_S3_ENDPOINT",
                    "AZURE_STORAGE_CONNECTION_STRING",
                    "AZURE_CLIENT_SECRET",
                    "AZURE_EMULATOR_ENDPOINT",
                    "ML_AZURE_EMULATOR_ENDPOINT",
                ]:
                    self.assertNotIn(key, service.get("environment", {}), name)
            self.assertEqual(services["prometheus"]["ports"][0]["host_ip"], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
