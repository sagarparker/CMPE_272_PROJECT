import unittest
from gate import evaluate


class GateTest(unittest.TestCase):
    catalog = {"vulnerabilities": [{"cveID": "CVE-2025-12345"}]}

    def test_known_exploited_is_blocked_even_without_a_fix_or_high_severity(self):
        report = {"Results": [{"Target": "pom.xml", "Vulnerabilities": [
            {"VulnerabilityID": "CVE-2025-12345", "Severity": "MEDIUM"}]}]}
        blocked, _ = evaluate(report, self.catalog)
        self.assertEqual(blocked[0]["cves"], ["CVE-2025-12345"])

    def test_vendor_aliases_are_checked(self):
        report = {"Results": [{"Vulnerabilities": [
            {"VulnerabilityID": "GHSA-example", "VendorIDs": ["CVE-2025-12345"]}]}]}
        self.assertTrue(evaluate(report, self.catalog)[0])

    def test_severity_alone_is_not_evidence_of_exploitation(self):
        report = {"Results": [{"Vulnerabilities": [
            {"VulnerabilityID": "CVE-2025-98765", "Severity": "CRITICAL"}]}]}
        self.assertEqual(evaluate(report, self.catalog), ([], []))

    def test_secret_values_are_not_retained(self):
        report = {"Results": [{"Secrets": [{"RuleID": "test", "Match": "SENSITIVE", "Code": "SENSITIVE", "StartLine": 1}]}]}
        _, secrets = evaluate(report, self.catalog)
        self.assertTrue(secrets)
        self.assertNotIn("SENSITIVE", str(report))
        self.assertNotIn("SENSITIVE", str(secrets))

    def test_missing_scan_or_catalog_fails_closed(self):
        with self.assertRaises(ValueError): evaluate({}, self.catalog)
        with self.assertRaises(ValueError): evaluate({"Results": []}, {"vulnerabilities": []})


if __name__ == "__main__":
    unittest.main()
