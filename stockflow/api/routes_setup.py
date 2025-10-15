# api/routes_setup.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from api.deps import get_db
from core.services.settings import SettingsService

router = APIRouter()

@router.get("/setup/company", response_class=HTMLResponse)
def setup_company_get(request: Request):
    db = get_db()
    ss = SettingsService(db)
    if ss.has_company_code():
        return RedirectResponse(url="/dashboard", status_code=303)

    # 初始渲染（无默认随机数，界面显示说明）
    return request.app.templates.TemplateResponse("setup_company.html", {
        "request": request,
        "suggest": "",
        "error": None
    })

@router.post("/setup/company", response_class=HTMLResponse)
def setup_company_post(request: Request,
                       company_name: str = Form(...),
                       abbrev_input: str = Form("")):
    db = get_db()
    ss = SettingsService(db)
    if ss.has_company_code():
        return RedirectResponse(url="/dashboard", status_code=303)

    # 计算缩写：优先手动；否则根据公司名建议
    abbrev = SettingsService.normalize_abbrev(abbrev_input)
    if not abbrev:
        abbrev = SettingsService.suggest_abbrev(company_name)

    if not abbrev:
        return request.app.templates.TemplateResponse("setup_company.html", {
            "request": request, "suggest": "",
            "error": "无法生成公司缩写，请手动输入 1~6 位的字母或数字。"
        })

    # 生成公司代码（缩写 + 4位随机数）
    code = SettingsService.gen_company_code(abbrev)

    # 持久化（公司名称、缩写、公司代码）
    ss.set("company_name", company_name.strip())
    ss.set("company_abbrev", abbrev)
    ss.set("company_code", code)

    return RedirectResponse(url="/dashboard", status_code=303)
