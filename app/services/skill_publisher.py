"""Skill 商品发布工具 — 自动打包并发布 SKILL.md 到 Alipay SkillPay.

使用方法::

    python -m app.services.skill_publisher list
    python -m app.services.skill_publisher publish beautiful-article
    python -m app.services.skill_publisher validate beautiful-article

目录结构要求::

    <skill_name>/
    ├── SKILL.md          ← 必须，标准格式
    ├── manifest.json     ← 可选，商品元数据
    └── README.md         ← 可选，用户说明
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

HERMES_SKILLS_DIR = Path(os.getenv("HERMES_SKILLS_DIR", str(Path.home() / ".hermes" / "skills")))
REPOS_DIR         = Path(os.getenv("REPOS_DIR", "/root/repos"))

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillManifest:
    name:        str
    version:     str
    description: str
    category:    str
    price:       float
    trigger:     list[str]
    author:      str
    homepage:    str
    compat:      list[str]
    tags:        list[str]

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "version":     self.version,
            "description": self.description,
            "category":    self.category,
            "price":       self.price,
            "trigger":     self.trigger,
            "author":      self.author,
            "homepage":    self.homepage,
            "compat":      self.compat,
            "tags":        self.tags,
        }


@dataclass(frozen=True)
class PublishResult:
    success:    bool
    skill_name: str
    skill_dir:  Path | None
    package_path: Path | None
    error:      str | None = None


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Skill 商品发布工具")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出所有可发布的 Skills")
    p = sub.add_parser("publish", help="发布一个 Skill 到 SkillPay")
    p.add_argument("skill", help="Skill 名称")
    p.add_argument("--dry-run", action="store_true", help="仅验证，不发布")
    p.add_argument("--price", type=float, default=None, help="设置价格（元）")

    v = sub.add_parser("validate", help="验证 Skill 格式")
    v.add_argument("skill", help="Skill 名称")

    args = parser.parse_args(argv)

    if args.cmd == "list":
        for skill in list_available_skills():
            print(f"  {skill}")
        return 0

    if args.cmd == "validate":
        result = validate_skill(args.skill)
        if result.success:
            print(f"✅ {result.skill_name} 格式验证通过")
            return 0
        else:
            print(f"❌ {result.error}")
            return 1

    if args.cmd == "publish":
        result = publish_skill(args.skill, dry_run=args.dry_run, price=args.price)
        if result.success:
            print(f"✅ {result.skill_name} 发布成功")
            if result.package_path:
                print(f"   安装包: {result.package_path}")
        else:
            print(f"❌ {result.error}")
        return 0 if result.success else 1

    parser.print_help()
    return 0


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def list_available_skills() -> list[str]:
    """返回 ~/.hermes/skills/ 中所有包含 SKILL.md 的目录名。"""
    skills = []
    for path in HERMES_SKILLS_DIR.iterdir():
        if path.is_dir() and (path / "SKILL.md").exists():
            skills.append(path.name)
    return sorted(skills)


def validate_skill(skill_name: str) -> PublishResult:
    """验证 Skill 目录格式，返回验证结果。"""
    skill_dir = HERMES_SKILLS_DIR / skill_name
    if not skill_dir.exists():
        return PublishResult(False, skill_name, None, None, f"目录不存在: {skill_dir}")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return PublishResult(False, skill_name, skill_dir, None, "缺少 SKILL.md")

    # Validate SKILL.md format
    try:
        text = skill_md.read_text(encoding="utf-8")
    except Exception as exc:
        return PublishResult(False, skill_name, skill_dir, None, f"无法读取 SKILL.md: {exc}")

    errors: list[str] = []

    # Check required frontmatter
    if not text.startswith("---"):
        errors.append("SKILL.md 必须以 YAML frontmatter (---) 开头")

    if "name:" not in text:
        errors.append("SKILL.md 缺少 name: 字段")

    if "description:" not in text:
        errors.append("SKILL.md 缺少 description: 字段")

    # Check skill name safety
    if "/" in skill_name or "\\" in skill_name:
        errors.append("Skill 名称不能包含路径分隔符")

    if not errors:
        return PublishResult(True, skill_name, skill_dir, None)
    return PublishResult(False, skill_name, skill_dir, None, "; ".join(errors))


def publish_skill(
    skill_name: str,
    *,
    dry_run: bool = False,
    price: float | None = None,
) -> PublishResult:
    """打包 Skill 并生成发布指南（支持手动上架到 SkillPay）。

    不自动提交到 SkillPay（需要登录 skillpay.alipay.com 操作），
    但会生成标准的 .tar.gz 安装包供上传使用。

    Args:
        skill_name:  Skills 目录名
        dry_run:     True=仅验证，False=生成安装包
        price:       建议价格（元），写入 manifest.json

    Returns:
        PublishResult with package_path on success.
    """
    # Validate first
    result = validate_skill(skill_name)
    if not result.success:
        return result

    skill_dir = result.skill_dir
    assert skill_dir is not None

    if dry_run:
        return result

    # Build manifest.json
    manifest = _build_manifest(skill_dir, skill_name, price=price)

    # Package as .tar.gz
    package_path = _package_skill(skill_dir, skill_name, manifest)
    if package_path is None:
        return PublishResult(False, skill_name, skill_dir, None, "打包失败")

    # Generate listing guide
    listing_md = _generate_listing_md(skill_name, skill_dir, manifest)
    guide_path = skill_dir / "LISTING_GUIDE.md"
    guide_path.write_text(listing_md, encoding="utf-8")
    logger.info("Generated listing guide: %s", guide_path)

    return PublishResult(
        success=True,
        skill_name=skill_name,
        skill_dir=skill_dir,
        package_path=package_path,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_manifest(
    skill_dir: Path,
    skill_name: str,
    price: float | None = None,
) -> dict:
    """从 SKILL.md 和 manifest.json 构建商品元数据。"""
    manifest_path = skill_dir / "manifest.json"
    meta: dict = {
        "name":        skill_name,
        "version":     "1.0.0",
        "description":  _extract_description(skill_dir / "SKILL.md"),
        "category":    "AI & Productivity",
        "price":       price or 19.9,
        "trigger":     _extract_triggers(skill_dir / "SKILL.md"),
        "author":      "Eric Guo",
        "homepage":    "https://github.com/gyc567/CryptoAggHarmonic",
        "compat":      [],
        "tags":        [],
    }

    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            meta.update({k: v for k, v in existing.items() if v})
        except Exception as exc:
            logger.warning("Failed to load manifest.json: %s", exc)

    return meta


def _extract_description(skill_md: Path) -> str:
    """从 SKILL.md 提取 description。"""
    try:
        text = skill_md.read_text(encoding="utf-8")
        # Try frontmatter description:
        if text.startswith("---"):
            end = text.index("---", 3)
            frontmatter = text[3:end]
            for line in frontmatter.splitlines():
                if line.strip().startswith("description:"):
                    return line.split("description:", 1)[1].strip().strip("\"'")
        # Fallback: first paragraph
        paragraphs = text.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if para and not para.startswith("---") and len(para) > 20:
                return para[:200]
    except Exception:
        pass
    return ""


def _extract_triggers(skill_md: Path) -> list[str]:
    """从 SKILL.md 提取触发关键词。"""
    try:
        text = skill_md.read_text(encoding="utf-8")
        triggers: list[str] = []
        # Look for trigger/use-when patterns
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("trigger"):
                triggers.append(stripped.split(":", 1)[1].strip().strip(".,"))
            elif "use when" in stripped.lower():
                triggers.append(stripped.split(":", 1)[-1].strip().strip(".,"))
        return list(dict.fromkeys(triggers))[:10]  # deduplicate, max 10
    except Exception:
        return []


def _package_skill(
    skill_dir: Path,
    skill_name: str,
    manifest: dict,
) -> Path | None:
    """将 Skill 目录打包为 .tar.gz，返回包路径。"""
    try:
        # Write manifest
        manifest_path = skill_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # Build archive
        out_dir = REPOS_DIR / "skill-packages"
        out_dir.mkdir(exist_ok=True)
        archive_path = out_dir / f"{skill_name}.tar.gz"

        with tarfile.open(archive_path, "w:gz") as tf:
            # Only include: SKILL.md, manifest.json, README.md, references/, scripts/
            include_dirs = {"references", "scripts", "assets", "templates", "theme-profiles"}
            for child in skill_dir.iterdir():
                if child.is_file() and child.suffix in (".md", ".json", ".yaml", ".yml"):
                    tf.add(child, arcname=f"{skill_name}/{child.name}")
                elif child.is_dir() and child.name in include_dirs:
                    tf.add(child, arcname=f"{skill_name}/{child.name}")

        logger.info("Packaged skill to %s", archive_path)
        return archive_path

    except Exception as exc:
        logger.error("Failed to package skill %s: %s", skill_name, exc)
        return None


def _generate_listing_md(skill_name: str, skill_dir: Path, manifest: dict) -> str:
    """生成 Alipay SkillPay 上架指南。"""
    desc = manifest.get("description", "")
    price = manifest.get("price", 19.9)
    triggers_str = ", ".join(manifest.get("trigger", [])[:5])
    return f"""# {skill_name} — SkillPay 上架指南

## 商品信息

| 字段 | 内容 |
|------|------|
| 商品名称 | {manifest['name']} |
| 版本 | {manifest['version']} |
| 定价 | ¥{price:.2f} |
| 类目 | {manifest['category']} |
| 作者 | {manifest['author']} |

## 商品描述

{desc}

## 触发关键词（用户在 AI Agent 中输入这些词来激活 Skill）

{triggers_str}

## 安装包

直接上传此目录下的文件到 SkillPay：
- SKILL.md（必须）
- manifest.json（自动生成）
- README.md（如有）

或使用预打包文件：
```
/root/repos/skill-packages/{skill_name}.tar.gz
```

## 履约脚本

购买后用户会通过 `alipay-bot` 自动安装到 `~/.hermes/skills/{skill_name}/`。

## 上架步骤

1. 登录 https://skillpay.alipay.com → 我是创作者
2. 点击「上架新 Skill」
3. 填写以上商品信息
4. 上传安装包或直接粘贴 SKILL.md 内容
5. 设置价格 ¥{price:.2f}
6. 提交审核

## 合规提示

- SKILL.md 不得包含付费内容或诱导购买的话术
- 确保你有该 Skill 的全部知识产权
- 上架前完成 SkillPay 协议 + AI 按量付费协议签署

---
Generated at {datetime.now(timezone.utc).isoformat()} UTC
""".strip()
