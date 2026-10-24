"""Pure entrypoint and image build-context checks; not Cloud Run deployment evidence."""
import importlib.util
from pathlib import Path
import unittest

LAB=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("lab007_container",LAB/"scripts/run-container.py")
entry=importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class ContainerTests(unittest.TestCase):
    def test_three_fixed_targets_and_bounded_processes(self):
        for role,target,threads in (
            ("portal","portal_runtime:build_portal()","4"),
            ("worker","queue_runtime:build_worker()","1"),
            ("dispatcher","queue_runtime:build_dispatcher()","1")):
            argv=entry.command({"SERVICE_ROLE":role,"PORT":"8080"})
            self.assertEqual(argv[-1],target)
            self.assertEqual(argv[argv.index("--workers")+1],"1")
            self.assertEqual(argv[argv.index("--threads")+1],threads)
            self.assertNotIn("--preload",argv)
            self.assertNotIn("--access-logfile",argv)
            self.assertEqual(argv[argv.index("--timeout")+1],"65")

    def test_rejects_shell_targets_invalid_ports_and_unbounded_digit_strings(self):
        for env in ({},{"SERVICE_ROLE":"bootstrap"},{"SERVICE_ROLE":"portal; echo secret"},
            *({"SERVICE_ROLE":"portal","PORT":p} for p in
              ("0","65536","80;echo secret","-1","１２３４","1"*10000,None,80))):
            with self.assertRaises(ValueError):
                entry.command(env)
        self.assertEqual(entry.command({"SERVICE_ROLE":"worker","PORT":"09000"})[2],"0.0.0.0:9000")

    def test_bootstrap_cloud_build_uses_separate_dockerfile_and_digest_substitution(self):
        config=(LAB/"cloudbuild-bootstrap.yaml").read_text()
        self.assertIn("gcr.io/cloud-builders/docker",config)
        self.assertIn("bootstrap/Dockerfile",config)
        self.assertIn("$" + "{_IMAGE}",config)
        self.assertIn("images:",config)
        self.assertIn("CLOUD_LOGGING_ONLY",config)

    def test_nonroot_image_and_allowlisted_context(self):
        docker=(LAB/"Dockerfile").read_text()
        self.assertIn("USER 10001:10001",docker)
        self.assertNotIn("COPY .",docker)
        ignore=(LAB/".dockerignore").read_text().splitlines()
        self.assertEqual(ignore[0],"**")
        self.assertNotIn("!sql/",ignore)
        self.assertNotIn("!tests/",ignore)
        self.assertNotIn("!scripts/create-secrets.py",ignore)
        self.assertIn("**/auth.json",ignore)


if __name__=="__main__":
    unittest.main()
