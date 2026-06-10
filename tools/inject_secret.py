"""构建辅助：检查许可证密钥是否存在。"""
from pathlib import Path


def main() -> None:
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "license_service.py"
    text = src.read_text(encoding="utf-8")
    if 'SECRET = "' not in text:
        raise SystemExit("SECRET not found")
    print("SECRET kept stable.")


if __name__ == "__main__":
    main()
