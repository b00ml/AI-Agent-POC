"""
通过 ERP 门户（Next.js server actions）创建开放平台 API Key。

用法：
    python tools/create_api_key.py --name "AI报销审核M2+M3全量" [--scopes scope1 scope2 ...]

默认勾选 M2+M3 所需的最小权限集：
    master-data:read expense:read expense:review approval:read attachment:read invoice:read

说明：ERP 门户登录信息必须从环境变量读取（QIHENG_PORTAL_URL /
QIHENG_PORTAL_USER / QIHENG_PORTAL_PASSWORD）。本工具不会提供默认账户或密码。
"""

import os
import re
import argparse

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_SCOPES = [
    "master-data:read",
    "expense:read",
    "expense:review",
    "approval:read",
    "attachment:read",
    "invoice:read",
]


def login(session: requests.Session, portal: str, user: str, password: str) -> None:
    """通过登录页 server action 建立会话"""
    r = session.get(portal + "/login", timeout=15)
    m = re.search(r'\$ACTION_ID_([0-9a-f]+)', r.text)
    if not m:
        raise RuntimeError("未找到登录 action id")
    resp = session.post(
        portal + "/login",
        files={
            "$ACTION_ID_" + m.group(1): (None, ""),
            "username": (None, user),
            "password": (None, password),
        },
        allow_redirects=False,
        timeout=15,
        headers={"Origin": portal},
    )
    if resp.status_code not in (302, 303) or "qh_session" not in session.cookies:
        raise RuntimeError(f"登录失败: HTTP {resp.status_code}")


def create_api_key(session: requests.Session, portal: str, name: str, scopes: list) -> str:
    """在开发者中心创建 API Key，返回密钥明文"""
    r = session.get(portal + "/developer", timeout=15)
    page_html = r.text
    # 定位「创建 API Key」表单（含 name 输入与 scopes 勾选框）
    idx = page_html.find('创建 API Key')
    if idx < 0:
        raise RuntimeError("未找到创建密钥表单")
    form_start = page_html.find("<form", idx)
    if form_start < 0:
        raise RuntimeError("未找到创建密钥表单（form）")
    form_end = page_html.find("</form>", idx)
    form_html = page_html[form_start:form_end]

    ref_m = re.search(r'name="\$ACTION_REF_(\d+)"', form_html)
    if not ref_m:
        raise RuntimeError("未找到创建密钥表单（ACTION_REF）")
    ref_id = ref_m.group(1)
    action0_m = re.search(rf'name="\$ACTION_{ref_id}:0" value="([^"]*)"', form_html)
    action1_m = re.search(rf'name="\$ACTION_{ref_id}:1" value="([^"]*)"', form_html)
    key_m = re.search(r'name="\$ACTION_KEY" value="([^"]*)"', form_html)
    if not (action0_m and action1_m and key_m):
        raise RuntimeError("未找到创建密钥表单（hidden fields）")
    action0, action1, action_key = action0_m.group(1), action1_m.group(1), key_m.group(1)

    files = [
        (f"$ACTION_REF_{ref_id}", (None, "")),
        (f"$ACTION_{ref_id}:0", (None, action0)),
        (f"$ACTION_{ref_id}:1", (None, action1)),
        ("$ACTION_KEY", (None, action_key)),
        ("name", (None, name)),
    ]
    for sc in scopes:
        files.append(("scopes", (None, sc)))

    resp = session.post(
        portal + "/developer",
        files=files,
        allow_redirects=False,
        timeout=20,
        headers={"Origin": portal},
    )
    text = resp.text
    m_secret = re.search(r"(qh_live_[A-Za-z0-9]+)", text)
    if m_secret:
        return m_secret.group(1)
    raise RuntimeError(f"创建失败: HTTP {resp.status_code} body={text[:300]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="创建 ERP 开放平台 API Key")
    parser.add_argument("--name", default="AI报销审核M2+M3全量", help="用途说明")
    parser.add_argument("--scopes", nargs="*", default=DEFAULT_SCOPES, help="授权范围")
    args = parser.parse_args()

    portal = os.getenv("QIHENG_PORTAL_URL")
    user = os.getenv("QIHENG_PORTAL_USER")
    password = os.getenv("QIHENG_PORTAL_PASSWORD")
    missing = [
        name for name, value in (
            ("QIHENG_PORTAL_URL", portal),
            ("QIHENG_PORTAL_USER", user),
            ("QIHENG_PORTAL_PASSWORD", password),
        ) if not value or value.startswith("your_")
    ]
    if missing:
        raise RuntimeError(f"缺少门户配置环境变量: {', '.join(missing)}")

    session = requests.Session()
    login(session, portal, user, password)
    secret = create_api_key(session, portal, args.name, args.scopes)
    print("密钥创建成功（仅显示一次，请妥善保存）:")
    print(secret)
    print("授权范围:", ", ".join(args.scopes))


if __name__ == "__main__":
    main()
