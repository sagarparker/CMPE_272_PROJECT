import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("configure_google", Path(__file__).with_name("configure-google.py"))
google = importlib.util.module_from_spec(spec)
spec.loader.exec_module(google)


class Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps(self.value).encode() if self.value is not None else b""


class GoogleConfigurationTests(unittest.TestCase):
    def test_updater_creates_then_updates_only_provider_and_mapper(self):
        providers, mappers, writes = [], [], []

        def call(request, timeout):
            path = request.full_url.removeprefix("http://keycloak/auth")
            if path.endswith("/token"):
                self.assertIn(b"password=operator-secret", request.data)
                return Response({"access_token": "operator-token"})
            self.assertEqual(request.get_header("Authorization"), "Bearer operator-token")
            self.assertEqual(request.get_header("X-forwarded-proto"), "https")
            if path.endswith("/clients?clientId=mediamesh-web"):
                return Response([{"id": "web-client"}])
            target = providers if "/identity-provider/instances" in path else mappers
            if request.method == "GET":
                return Response(target)
            self.assertIn(request.method, ("POST", "PUT"))
            body = json.loads(request.data)
            writes.append((request.method, path))
            if target is providers:
                body["internalId"] = "google-id"
            else:
                body["id"] = "mapper-id"
            target[:] = [body]
            return Response(None)

        with patch.object(google.urllib.request, "urlopen", side_effect=call):
            for _ in range(2):
                google.configure("http://keycloak/auth", "mediamesh", "operator", "operator-secret", "google-client", "google-secret", "archive.example.org")
        self.assertEqual([method for method, _ in writes], ["POST", "POST", "PUT", "PUT"])
        self.assertEqual(providers[0]["config"]["clientId"], "google-client")
        self.assertEqual(providers[0]["config"]["clientSecret"], "google-secret")
        self.assertTrue(providers[0]["trustEmail"])
        self.assertEqual(mappers[0]["config"]["user.session.note"], "identity_provider")
        self.assertEqual(mappers[0]["config"]["claim.name"], "identity_provider")
        self.assertTrue(all("users" not in path for _, path in writes))


if __name__ == "__main__":
    unittest.main()
