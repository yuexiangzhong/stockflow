# api/server.py
# 应用入口

from pathlib import Path
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.deps import get_cfg, get_services, current_user, get_db
from utils.security import issue_jwt


def create_app() -> FastAPI:
    app = FastAPI(title="StockFlow Web")

    # —— 模板 —— #
    templates = Jinja2Templates(directory="api/templates")
    app.templates = templates  # 供路由里通过 request.app.templates 使用

    # —— 确保静态资源目录存在后再挂载（自动创建） —— #
    Path("api/static").mkdir(parents=True, exist_ok=True)
    Path("data/photos").mkdir(parents=True, exist_ok=True)

    # —— 静态资源 —— #
    app.mount("/static", StaticFiles(directory="api/static"), name="static")
    # 照片目录
    app.mount("/photos", StaticFiles(directory="data/photos"), name="photos")

    # —— 公司初始化强制引导中间件 —— #
    @app.middleware("http")
    async def company_setup_guard(request: Request, call_next):
        """
        若尚未设置 company_code，则除允许的路径之外全部重定向到 /setup/company
        允许路径：/setup/company、/static、/photos、/login、/logout、/favicon.ico
        """
        path = request.url.path
        allow_prefix = [
            "/setup/company",
            "/static",
            "/photos",
            "/login",
            "/logout",
            "/favicon.ico",
        ]
        if any(path.startswith(p) for p in allow_prefix):
            return await call_next(request)

        # 若没有 setup 路由文件也直接放行（开发态容错）
        has_setup = False
        try:
            from api.routes_setup import router as _  # noqa
            has_setup = True
        except Exception:
            has_setup = False

        if not has_setup:
            return await call_next(request)

        # 检查 settings 里的 company_code
        db = get_db()
        try:
            with db.connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT value FROM settings WHERE key='company_code' LIMIT 1")
                row = cur.fetchone()
                if not row or not (row["value"] or "").strip():
                    return RedirectResponse(url="/setup/company", status_code=303)
        except Exception:
            # settings 表未建或查询异常时，仍跳设置页
            return RedirectResponse(url="/setup/company", status_code=303)

        return await call_next(request)

    # —— 基础页面 —— #
    @app.get("/", response_class=HTMLResponse)
    def root(request: Request):
        return RedirectResponse(url="/dashboard")

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return templates.TemplateResponse("login.html", {"request": request, "error": None})

    @app.post("/login", response_class=HTMLResponse)
    def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        remember: str = Form(None),
    ):
        cfg = get_cfg()
        inv, auth = get_services()
        user = auth.authenticate(username, password)
        if not user:
            return templates.TemplateResponse(
                "login.html", {"request": request, "error": "用户名或密码错误"}
            )
        # 签发 JWT，写 Cookie
        sec = cfg.security
        minutes = sec["access_token_minutes"]
        if remember:
            minutes = sec["refresh_token_days"] * 24 * 60
        token = issue_jwt(
            {"id": user["id"], "username": user["username"], "roles": user["roles"]},
            sec["secret_key"],
            minutes,
        )
        resp = RedirectResponse(url="/dashboard", status_code=302)
        resp.set_cookie(key=sec["cookie_name"], value=token, httponly=True, samesite="lax")
        return resp

    @app.get("/logout")
    def logout():
        cfg = get_cfg()
        sec = cfg.security
        resp = RedirectResponse(url="/login", status_code=302)
        resp.delete_cookie(sec["cookie_name"])
        return resp

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request, user=Depends(current_user)):
        return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})

    # —— 路由挂载（在中间件之后 include） —— #
    # 可选：公司初始化路由
    try:
        from api.routes_setup import router as setup_router
        app.include_router(setup_router, prefix="", tags=["setup"])
    except Exception:
        pass  # 没有该文件时忽略

    # 标签打印相关路由
    try:
        from api.routes_labels import router as labels_router
        app.include_router(labels_router, prefix="", tags=["labels"])
    except Exception as e:
        # 若模块缺失或导入异常，不影响服务启动；需要时可打印日志
        # print(f"[routes_labels] import failed: {e}")
        pass

    # 库存相关路由
    try:
        from api.routes_inventory import router as inv_router
        app.include_router(inv_router, prefix="", tags=["inventory"])
    except Exception:
        pass

    # 二维码路由（含 PNG 和 SVG）
    try:
        from api.routes_qr import router as qr_router
        app.include_router(qr_router, prefix="", tags=["qr"])
    except Exception:
        pass

    return app


# uvicorn 入口所需全局变量
app = create_app()
