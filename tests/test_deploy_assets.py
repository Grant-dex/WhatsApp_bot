"""部署产物的静态校验（本机没有 Docker，只能验证引用与配置是否自洽）。"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DeployAssetsTest(unittest.TestCase):
    def test_dockerfile_references_existing_files(self):
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("requirements.txt", text)
        self.assertIn("src/web_main.py", text)
        # 这些是构建/运行必需的路径
        self.assertTrue((ROOT / "requirements.txt").exists())
        self.assertTrue((ROOT / "src" / "web_main.py").exists())
        self.assertTrue((ROOT / "bridge" / "package.json").exists())

    def test_compose_binds_loopback_only(self):
        data = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        service = data["services"]["whatsapp-bot"]
        self.assertTrue(all(port.startswith("127.0.0.1:") for port in service["ports"]),
                        "不该把 8000 直接暴露到公网")
        self.assertIn("/data", service["volumes"][0])

    def test_dockerignore_keeps_secrets_out(self):
        text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        for pattern in ("data", ".venv", "**/__pycache__"):
            self.assertIn(pattern, text)

    def test_deploy_doc_exists(self):
        doc = ROOT / "docs" / "DEPLOY.md"
        self.assertTrue(doc.exists())
        body = doc.read_text(encoding="utf-8")
        for keyword in ("docker compose", "cloudflared", "Access", "备份"):
            self.assertIn(keyword, body)


if __name__ == "__main__":
    unittest.main()
