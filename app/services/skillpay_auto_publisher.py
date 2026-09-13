"""
Alipay SkillPay Auto-Publisher v2
Complete automation using browser-intercepted API structure
"""
import json
import subprocess
import time
import os
import re
from typing import Optional

# Cookie string (from browser session)
COOKIE_STRING = (
    "ALIPAYJSESSIONID=RZ436327XWV1XsRtOYOPYuaMwjYKzmauthRZ54GZ00; "
    "ctoken=XinfBg7mLlrAii_6; "
    "rtk=0Ltxp8ysNxixVGwhXLxcytxEfiRW0qaE5gAPNhgJGzYFQB4cGlP; "
    "_CHIPS-ALIPAYJSESSIONID=RZ436327XWV1XsRtOYOPYuaMwjYKzmauthRZ54GZ00; "
    "zone=RZ43A; "
    "spanner=3Z6jErPZdKuySTQ75QPIvMAvJnoWmKlK4EJoL7C0n0A=; "
    "jsh_t_c_e=jsh_t_0.27368366211022355; "
    "752459860=xXo9fGYl6CSzQLvGrmZfGsU%3DL7Jr6GE7fCUE51efwLmd"
)

API_BASE = "https://aipayapi.alipay.com"
HEADERS_BASE = [
    "Content-Type: application/json",
    "Accept: application/json",
    f"Cookie: {COOKIE_STRING}",
    "Referer: https://skillpay.alipay.com/creator/product-new",
    "Origin: https://skillpay.alipay.com",
]


def curl(method: str, path: str, data: dict = None, base: str = None) -> dict:
    """Make API call via curl"""
    url = f"{(base or API_BASE)}{path}"
    cmd = ["curl", "-s", "-X", method, url]
    for h in HEADERS_BASE:
        cmd += ["-H", h]
    if data:
        cmd += ["-d", json.dumps(data, ensure_ascii=False)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return json.loads(result.stdout)
    except:
        return {"raw": result.stdout[:500]}


def upload_skill_file(zip_path: str) -> Optional[str]:
    """
    Upload skill .zip file to Alipay CDN
    Returns: CDN URL for the file
    """
    if not os.path.exists(zip_path):
        return None
    
    # Use curl to upload
    cmd = [
        "curl", "-s", "-X", "POST",
        "https://skillpay.alipay.com/skillpay/skillfile/upload.json",
        "-H", f"Cookie: {COOKIE_STRING}",
        "-H", "Referer: https://skillpay.alipay.com/creator/product-new",
        "-F", f"file=@{zip_path}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    try:
        resp = json.loads(result.stdout)
        if resp.get("success"):
            url = resp.get("data", {}).get("url") or resp.get("fileUrl")
            print(f"  ✓ 文件上传成功: {url}")
            return url
        else:
            print(f"  ✗ 文件上传失败: {resp.get('errorMsg', resp.get('msg', 'unknown'))}")
            return None
    except:
        print(f"  ✗ 上传响应解析失败: {result.stdout[:200]}")
        return None


def check_sign_status(product_code: str) -> dict:
    """Check signing status"""
    return curl("GET", f"/skillpay/sign/status?productCode={product_code}")


def list_skills(page_num: int = 1, page_size: int = 20) -> dict:
    """List all skills"""
    return curl("POST", "/skillpay/skills/list.json", data={"pageNum": page_num, "pageSize": page_size})


def create_skill_product(
    title: str,
    description: str,
    price_yuan: float,
    skill_cdn_url: str = None,
    billing_mode: str = "ONE_TIME",
) -> dict:
    """
    Create a skill product
    
    Args:
        title: Product title
        description: Short description (≤500 chars)
        price_yuan: Price in yuan
        skill_cdn_url: CDN URL from uploaded skill file
        billing_mode: ONE_TIME or SUBSCRIPTION
    """
    price_fen = int(price_yuan * 100)
    
    body = {
        "productType": "SKILL",
        "profile": {
            "title": title,
            "shortDescription": description[:500],
            "extraParams": {
                "source_skills": skill_cdn_url or "",
                "desc_skills": ""
            }
        },
        "fulfillment": {
            "fulfillmentMode": "SYNC",
            "deliveryType": "STRUCTURED_DATA",
            "endpoint": "https://skillpay.alipay.com/",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "timeoutSeconds": 30,
            "maxWaitSeconds": 30
        },
        "extensionApis": [],
        "labels": [],
        "sortOrder": 100,
        "specifications": [{
            "specId": "SPEC-DEFAULT",
            "specName": "套餐规格",
            "required": True,
            "options": [{
                "optionId": "OPTION-DEFAULT",
                "label": "永久使用权" if billing_mode == "ONE_TIME" else "月度会员",
                "description": "一次性购买，永久使用 Skill" if billing_mode == "ONE_TIME" else "按月订阅使用",
                "metering": {
                    "unitName": "request",
                    "unitNameDisplay": "次",
                    "includedQuota": 1 if billing_mode == "ONE_TIME" else 1000
                }
            }]
        }],
        "pricingPlans": [{
            "planId": "PLAN-DEFAULT",
            "billingMode": billing_mode,
            "currency": "CNY",
            "displayPrice": {"amount": price_fen, "currency": "CNY"},
            "priceConfigJson": json.dumps(
                {"one_time": {"amount": price_fen, "currency": "CNY", "trialTimes": 0}}
                if billing_mode == "ONE_TIME"
                else {"subscription": {"amount": price_fen, "currency": "CNY", "interval": "MONTH", "trialTimes": 0}}
            ),
            "specOptions": [{"specOptionId": "OPTION-DEFAULT", "specId": "SPEC-DEFAULT"}],
            "enabled": True,
            "isDefault": True
        }],
        "skus": [{
            "skuId": "SKU-DEFAULT",
            "status": "ON_SALE",
            "specOptions": [{"specOptionId": "OPTION-DEFAULT", "specId": "SPEC-DEFAULT"}],
            "availablePlanIds": ["PLAN-DEFAULT"]
        }]
    }
    
    resp = curl("POST", "/skillpay/skill/createProduct.json", data=body)
    
    if resp.get("success"):
        product_id = resp.get("data", {}).get("productId") or resp.get("productId")
        print(f"  ✓ 商品创建成功: productId={product_id}")
        return {"success": True, "productId": product_id, "data": resp.get("data", {})}
    else:
        print(f"  ✗ 商品创建失败: {resp.get('errorMsg', resp.get('msg', 'unknown'))}")
        return {"success": False, "error": resp}


def submit_for_review(product_id: str) -> dict:
    """Submit product for review"""
    resp = curl("POST", f"/skillpay/skill/submitForReview.json?productId={product_id}")
    
    if resp.get("success") or resp.get("code") == "10000":
        print(f"  ✓ 提交审核成功")
        return {"success": True, "data": resp}
    else:
        print(f"  ✗ 提交审核失败: {resp.get('errorMsg', resp.get('msg', 'unknown'))}")
        return {"success": False, "error": resp}


def publish_skill(
    title: str,
    description: str,
    price_yuan: float,
    skill_zip_path: str = None,
    billing_mode: str = "ONE_TIME",
) -> dict:
    """
    Complete publish pipeline: upload + create + submit for review
    """
    print(f"\n{'='*50}")
    print(f"发布商品: {title} @ ¥{price_yuan}")
    print(f"{'='*50}")
    
    # Step 1: Check sign status
    print("\n[1/4] 检查签约状态...")
    for code in ["PAY_BY_SKILL", "PAY_BY_API"]:
        r = check_sign_status(code)
        data = r.get("data", {})
        status = data.get("signStatus", "UNKNOWN")
        signed = data.get("signed", False)
        print(f"  {code}: signStatus={status}, signed={signed}")
        if not signed:
            return {"success": False, "error": f"{code} 未签约"}
    
    # Step 2: Upload skill file
    skill_cdn_url = None
    if skill_zip_path:
        print("\n[2/4] 上传 Skill 文件...")
        skill_cdn_url = upload_skill_file(skill_zip_path)
        if not skill_cdn_url:
            print("  ⚠ 文件上传失败，继续（文件可能已存在）")
    
    # Step 3: Create product
    print("\n[3/4] 创建商品...")
    result = create_skill_product(title, description, price_yuan, skill_cdn_url, billing_mode)
    if not result.get("success"):
        return result
    product_id = result["productId"]
    
    # Step 4: Submit for review
    print("\n[4/4] 提交审核...")
    submit_for_review(product_id)
    
    # Verify
    time.sleep(2)
    skills = list_skills()
    my_skills = [
        s for s in skills.get("data", {}).get("page", {}).get("list", [])
        if s.get("productId") == product_id
    ]
    
    if my_skills:
        status = my_skills[0].get("status", "UNKNOWN")
        price = my_skills[0].get("price", "N/A")
        print(f"\n✓ 商品状态: {status}")
        print(f"  productId: {product_id}")
        print(f"  价格: ¥{price}")
        return {"success": True, "productId": product_id, "reviewStatus": status, "data": my_skills[0]}
    
    return {"success": True, "productId": product_id, "reviewStatus": "SUBMITTED"}


def make_skill_zip(skill_dir: str, output_path: str) -> str:
    """Package a skill directory into a zip file"""
    import zipfile
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(skill_dir):
            # Skip node_modules, .git
            dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', '__pycache__']]
            for f in files:
                fp = os.path.join(root, f)
                arcname = os.path.relpath(fp, skill_dir)
                z.write(fp, arcname)
    return output_path


if __name__ == "__main__":
    import sys
    
    print("=== Alipay SkillPay Auto-Publisher ===\n")
    
    # Check sign status first
    print("[签约状态]")
    for code in ["PAY_BY_SKILL", "PAY_BY_API"]:
        r = check_sign_status(code)
        data = r.get("data", {})
        print(f"  {code}: signStatus={data.get('signStatus')}, signed={data.get('signed')}")
    
    # List existing skills
    print("\n[现有商品]")
    r = list_skills()
    items = r.get("data", {}).get("page", {}).get("list", [])
    print(f"  共 {len(items)} 个商品")
    for item in items:
        print(f"  - {item.get('title')} | {item.get('productId')} | ¥{item.get('price', 'N/A')} | {item.get('status')}")
    
    # If called with args, publish a skill
    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "publish":
            title = sys.argv[2] if len(sys.argv) > 2 else "精美文章生成器"
            price = float(sys.argv[3] if len(sys.argv) > 3 else 19.9)
            zip_path = sys.argv[4] if len(sys.argv) > 4 else "/tmp/beautiful-article.zip"
            
            # Make zip if needed
            skill_zip = zip_path
            if not zip_path.endswith('.zip'):
                skill_zip = "/tmp/skill_package.zip"
                make_skill_zip(zip_path, skill_zip)
            
            result = publish_skill(
                title=title,
                description=f"优质的 {title}，基于 AI 技术构建",
                price_yuan=price,
                skill_zip_path=skill_zip,
                billing_mode="ONE_TIME",
            )
            print(f"\n结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
