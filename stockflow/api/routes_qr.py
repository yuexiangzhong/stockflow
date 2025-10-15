# api/routes_qr.py
import hmac
import hashlib
from base64 import b32encode
from io import BytesIO
from typing import Optional, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.deps import get_db, get_cfg

router = APIRouter()


# ----------------------------
# 载荷与校验码（沿用你现有规则）
# ----------------------------
def _make_chk(secret: str, comp: str, sku: str) -> str:
    """
    计算 HMAC-SHA256 校验值，取前 6 个 base32 字符（约 30 bit），
    足以防止误录与低概率冲突。
    """
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{comp}|{sku}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return b32encode(mac)[:6].decode("ascii")


def build_qr_payload(comp: str, sku: str, secret: str) -> str:
    """
    构建二维码载荷：SF1:<COMP>:<SKU>:<CHK>
    """
    chk = _make_chk(secret, comp, sku)
    return f"SF1:{comp}:{sku}:{chk}"


# ----------------------------
# DB 读写小工具
# ----------------------------
def _get_company_code() -> str:
    db = get_db()
    with db.connect() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT value FROM settings WHERE key='company_code' LIMIT 1"
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="未设置公司代码")
        return (row["value"] or "").strip()


def _get_qr_payload_or_build(sku: str) -> str:
    """
    优先使用 products.qr_payload；若无则按规则即时构建（不落库）。
    """
    db = get_db()
    cfg = get_cfg()
    company_code = _get_company_code()
    secret = cfg.security["secret_key"]

    with db.connect() as conn:
        cur = conn.cursor()
        prow = cur.execute(
            "SELECT qr_payload FROM products WHERE sku=? LIMIT 1", (sku,)
        ).fetchone()
        if prow and prow["qr_payload"]:
            return prow["qr_payload"]

    # 回退：即时构建
    return build_qr_payload(company_code, sku, secret)


# ----------------------------
# PNG 二维码（保留你现有接口）
# GET /qr/{sku}.png
# ----------------------------
@router.get("/qr/{sku}.png")
def qr_png(sku: str):
    """
    动态生成二维码 PNG，内容为 SF1:<COMP>:<SKU>:<CHK>
    """
    try:
        import qrcode  # pillow 作为其依赖
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="缺少依赖：qrcode，请先安装 pip install qrcode pillow",
        )

    payload = _get_qr_payload_or_build(sku)

    # 二值色、小边距，扫码效果更稳
    qr = qrcode.QRCode(
        border=2, box_size=6, error_correction=qrcode.constants.ERROR_CORRECT_M
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


# ----------------------------
# SVG 二维码（新增给打印用）
# GET /qr-svg/{sku}.svg
# ----------------------------
@router.get("/qr-svg/{sku}.svg")
def qr_svg(sku: str):
    """
    生成 SVG 矢量二维码（打印更清晰，无缩放损失）。
    内容同 PNG：SF1:<COMP>:<SKU>:<CHK>
    """
    try:
        import qrcode
        import qrcode.image.svg as qsvg
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="缺少依赖：qrcode（包含 svg 子模块），请先安装 pip install qrcode",
        )

    payload = _get_qr_payload_or_build(sku)

    # 说明：
    # - SvgImage 输出路径较简洁，适合嵌入 <img src="..."> 或 <object>；
    # - box_size 控制单个模块的矢量尺寸，打印页可按需要放大/缩小；
    factory = qsvg.SvgImage
    img = qrcode.make(payload, image_factory=factory, box_size=4, border=1)
    svg_bytes = img.to_string()

    return Response(content=svg_bytes, media_type="image/svg+xml")
