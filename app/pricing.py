"""Decimal报价权威计算：逐行舍入、合计、计税。"""
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fastapi import APIRouter, Request

from .core import DomainError
from .schemas import QuoteSave

router = APIRouter(prefix="/api/projects", tags=["商务报价"])
CENT = Decimal("0.01")


def decimal_input(value: str, places: int, maximum: str, label: str):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,16}(?:\.\d{1," + str(places) + r"})?", value, flags=re.ASCII):
        raise DomainError("INVALID_DECIMAL", f"{label}须为非负十进制字符串，最多{places}位小数，不接受指数或NaN", 422)
    number = Decimal(value)
    if not number.is_finite() or number < 0 or number > Decimal(maximum):
        raise DomainError("DECIMAL_RANGE", f"{label}超出允许范围", 422)
    return number


def calculate_quote(lines, tax_rate):
    with localcontext() as context:
        context.prec = 40
        rate = decimal_input(tax_rate, 6, "1", "税率")
        calculated = []
        subtotal = Decimal("0.00")
        for line in lines:
            line = dict(line)
            quantity = decimal_input(line["quantity"], 3, "1000000", "数量")
            price = decimal_input(line["unit_price"], 2, "1000000000", "单价")
            amount = (quantity * price).quantize(CENT, rounding=ROUND_HALF_UP)
            if amount > Decimal("1000000000000"):
                raise DomainError("QUOTE_LIMIT", "单行金额超出一万亿元安全上限", 422)
            subtotal += amount
            line.update(quantity=format(quantity, "f"), unit_price=format(price, ".2f"), amount=format(amount, ".2f"))
            calculated.append(line)
        if subtotal > Decimal("1000000000000"):
            raise DomainError("QUOTE_LIMIT", "不含税合计超出一万亿元安全上限", 422)
        tax = (subtotal * rate).quantize(CENT, rounding=ROUND_HALF_UP)
        return {"lines": calculated, "subtotal": format(subtotal, ".2f"), "tax_rate": format(rate, "f"),
                "tax": format(tax, ".2f"), "total": format(subtotal + tax, ".2f"), "currency": "CNY",
                "rounding": "ROUND_HALF_UP：每行至分后合计，税额在合计基础上至分"}


def quote_text(quote):
    if not quote:
        return "【待填：服务报价及明确税率】"
    lines = [f"{x['name']}：{x['quantity']}{x['unit']} × {x['unit_price']}元 = {x['amount']}元；依据：{x['basis']}" for x in quote["lines"]]
    lines += [f"不含税合计：{quote['subtotal']}元", f"税率：{quote['tax_rate']}；税额：{quote['tax']}元",
              f"含税总价：{quote['total']}元", "税率确认依据：" + quote["tax_note"]]
    if not quote["tax_confirmed"]:
        lines.append("【待填：税率尚未人工确认】")
    return "\n".join(lines)


@router.get("/{project_id}/quote")
def quote_get(project_id: str, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id)
        return {"item": store.get(c, "quote", project_id, False), "project_version": p["version"]}


@router.put("/{project_id}/quote")
def quote_save(project_id: str, body: QuoteSave, request: Request):
    store = request.app.state.store
    with store.transaction() as c:
        p = store.project(c, project_id, body.expected_version, True)
        old = store.get(c, "quote", project_id, False)
        if body.entity_version != (old["version"] if old else 0):
            raise DomainError("VERSION_CONFLICT", "报价版本已变化，请刷新", 409)
        expected_fee = "supervision_service" if p["business_type"] == "supervision" else "tis_service"
        if body.fee_type != expected_fee or any("保险" in line.name or "保费" in line.name for line in body.lines):
            raise DomainError("FEE_TYPE_MISMATCH", "监理费、TIS技术服务费与保险保费不得混写；首期不测算保险保费", 422)
        calculated = calculate_quote([line.model_dump() for line in body.lines], body.tax_rate)
        item = store.save(c, "quote", {"id": project_id, "project_id": project_id, **calculated,
            "fee_type": body.fee_type, "tax_confirmed": body.tax_confirmed, "tax_note": body.tax_note})
        return {"item": item, "project": store.touch(c, p, "报价变化，正文与导出需重新生成使用同一快照")}
