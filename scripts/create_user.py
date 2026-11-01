#!/usr/bin/env python3
"""命令行创建账号（注册关闭后用这个加人）。

用法：
    python scripts/create_user.py someone@example.com
    python scripts/create_user.py someone@example.com --password 'my-pass-123'
    python scripts/create_user.py --list
    python scripts/create_user.py someone@example.com --data-dir ./data

不指定密码时会随机生成一个，并打印出来（只显示一次）。
账号对应的租户目录会自动创建：<data>/tenants/<user_id>/。
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    parser = argparse.ArgumentParser(description="创建 / 查看控制台账号")
    parser.add_argument("email", nargs="?", help="要创建的邮箱")
    parser.add_argument("--password", help="指定密码（至少 8 位），不填则随机生成")
    parser.add_argument("--data-dir", default=str(ROOT / "data"),
                        help="数据目录，默认项目下的 data/")
    parser.add_argument("--list", action="store_true", help="列出已有账号")
    parser.add_argument("--owner", action="store_true", help="标记为管理员（接管已有 data/）")
    args = parser.parse_args()

    os.environ["WHATSAPP_BOT_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())

    import accounts
    import tenancy

    if args.list or not args.email:
        users = accounts.list_users()
        if not users:
            print("还没有任何账号。")
        for user in users:
            flag = " [owner]" if user.get("is_owner") else ""
            print(f"{user['email']}{flag}  ->  {user['data_dir']}")
        return 0

    email = args.email.strip().lower()
    if accounts.get_user_by_email(email):
        print(f"账号已存在：{email}", file=sys.stderr)
        return 1

    password = args.password or secrets.token_urlsafe(12)
    if len(password) < 8:
        print("密码至少 8 位", file=sys.stderr)
        return 1

    if args.owner:
        data_dir = tenancy.base_data_dir()
        (data_dir / "logs").mkdir(parents=True, exist_ok=True)
        user_id = None
    else:
        user_id = secrets.token_hex(16)
        template = ROOT / "config.yaml"
        data_dir = tenancy.ensure_tenant_dir(user_id, template=template)

    user = accounts.create_user(email, password, data_dir,
                                is_owner=args.owner, user_id=user_id)
    print("账号已创建")
    print(f"  邮箱：{user['email']}")
    print(f"  密码：{password}")
    print(f"  数据目录：{user['data_dir']}")
    print("\n请把邮箱和密码发给对方，登录后请他自行修改（暂未提供改密页）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
