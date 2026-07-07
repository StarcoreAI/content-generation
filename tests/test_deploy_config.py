import os
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


def read_text(path):
    with open(os.path.join(ROOT, path), "r", encoding="utf-8") as f:
        return f.read()


class DeployConfigTests(unittest.TestCase):
    def test_dockerfile_runs_flask_app_with_one_gunicorn_worker(self):
        dockerfile = read_text("Dockerfile")
        requirements = read_text("requirements.txt")

        self.assertIn("FROM python:3.12-slim", dockerfile)
        self.assertIn("pip install --no-cache-dir -r requirements.txt", dockerfile)
        self.assertIn("GEO_HOST=0.0.0.0", dockerfile)
        self.assertIn("GEO_PORT=5000", dockerfile)
        self.assertIn("gunicorn", requirements)
        self.assertIn("--workers", dockerfile)
        self.assertIn("1", dockerfile)
        self.assertIn("app:app", dockerfile)

    def test_compose_mounts_persistent_data_and_maps_local_8080(self):
        compose = read_text("docker-compose.yml")

        self.assertIn("8080:5000", compose)
        self.assertIn("./data:/app/data", compose)
        self.assertIn("./pdf:/app/pdf", compose)
        self.assertIn("./logs:/app/logs", compose)
        self.assertIn(".env", compose)

    def test_env_example_and_deploy_readme_cover_cloud_trial_basics(self):
        env_example = read_text(".env.example")
        readme = read_text(os.path.join("deploy", "README.md"))

        self.assertIn("GEO_SECRET_KEY=replace-with-a-long-random-secret", env_example)
        self.assertIn("GEO_PORT=5000", env_example)
        self.assertNotIn("sk-", env_example)
        self.assertNotIn("api_key", env_example.lower())

        self.assertIn("docker compose up -d --build", readme)
        self.assertIn("gunicorn --bind 0.0.0.0:5000 --workers 1", readme)
        self.assertIn("data/", readme)
        self.assertIn("pdf/", readme)
        self.assertIn("logs/", readme)
        self.assertIn("一个 worker", readme)


if __name__ == "__main__":
    unittest.main()
