import importlib.util
from pathlib import Path
import unittest

LAB = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("container_entry", LAB / "scripts/run-container.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class ContainerTests(unittest.TestCase):
    def test_portal_and_worker_have_one_worker_and_explicit_thread_budgets(self):
        for role, threads, target in [("portal", "8", "portal_runtime:build_portal()"),
                                       ("worker", "1", "worker_http:build_app()")]:
            args = entry.command({"SERVICE_ROLE": role, "PORT": "8080"})
            self.assertEqual(args[args.index("--threads")+1], threads)
            self.assertEqual(args[args.index("--workers")+1], "1")
            self.assertEqual(args[-1], target)
            self.assertNotIn("--access-logfile", args)
            self.assertEqual(args[args.index("--bind")+1], "0.0.0.0:8080")

    def test_invalid_role_and_port_cannot_become_shell_arguments(self):
        for env in [{}, {"SERVICE_ROLE": "unknown"},
                    {"SERVICE_ROLE": "portal", "PORT": "0"},
                    {"SERVICE_ROLE": "worker", "PORT": "65536"},
                    {"SERVICE_ROLE": "portal", "PORT": "8080;cat /secrets/auth"}]:
            with self.subTest(env=env), self.assertRaises(ValueError):
                entry.command(env)

    def test_dockerfile_uses_explicit_copies_and_nonroot_identity(self):
        source = (LAB / "Dockerfile").read_text()
        self.assertIn("USER 10001:10001", source)
        self.assertNotIn("COPY . ", source)
        self.assertIn("COPY app/ /srv/app/", source)
        self.assertNotIn("create-secrets.py", source)
        self.assertNotIn("secrets/", source)
        self.assertIn('ENTRYPOINT ["python", "/srv/run-container.py"]', source)


if __name__ == "__main__":
    unittest.main()
