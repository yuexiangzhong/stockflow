import argparse
from utils.config import load_config
from infra.db_interface import DB, run_migrations
from core.services.inventory import InventoryService

def get_service():
    cfg = load_config()
    db = DB(cfg.database_path)
    run_migrations(db)
    return InventoryService(db)

def main():
    parser = argparse.ArgumentParser(prog="stockflow", description="StockFlow 出入库最小CLI")
    sub = parser.add_subparsers(dest="cmd")

    # product add
    p_add = sub.add_parser("product-add", help="新增商品")
    p_add.add_argument("--sku", required=True)
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--spec")
    p_add.add_argument("--unit", default="pcs")
    p_add.add_argument("--cost", type=float, default=0.0)
    p_add.add_argument("--price", type=float, default=0.0)

    # product list
    sub.add_parser("product-list", help="商品列表")

    # warehouse add
    w_add = sub.add_parser("wh-add", help="新增仓库")
    w_add.add_argument("--code", required=True)
    w_add.add_argument("--name", required=True)

    # inbound
    ib = sub.add_parser("inbound", help="入库")
    ib.add_argument("--product-id", type=int, required=True)
    ib.add_argument("--wh-id", type=int, required=True)
    ib.add_argument("--qty", type=float, required=True)

    # outbound
    ob = sub.add_parser("outbound", help="出库")
    ob.add_argument("--product-id", type=int, required=True)
    ob.add_argument("--wh-id", type=int, required=True)
    ob.add_argument("--qty", type=float, required=True)

    # stock show
    ss = sub.add_parser("stock", help="查询库存")
    ss.add_argument("--product-id", type=int, required=True)
    ss.add_argument("--wh-id", type=int, required=True)

    args = parser.parse_args()
    svc = get_service()

    if args.cmd == "product-add":
        pid = svc.add_product(args.sku, args.name, args.spec, args.unit, args.cost, args.price)
        print(f"✅ 新增商品 ID={pid}")
    elif args.cmd == "product-list":
        rows = svc.list_products()
        if not rows: print("（空）"); return
        for r in rows:
            print(f"[{r['id']}] {r['sku']} {r['name']} ({r.get('spec') or ''}) unit={r['unit']} cost={r['cost_price']} price={r['sale_price']}")
    elif args.cmd == "wh-add":
        wid = svc.add_warehouse(args.code, args.name)
        print(f"✅ 新增仓库 ID={wid}")
    elif args.cmd == "inbound":
        svc.inbound(args.product_id, args.wh_id, args.qty)
        print("✅ 入库完成")
    elif args.cmd == "outbound":
        svc.outbound(args.product_id, args.wh_id, args.qty)
        print("✅ 出库完成")
    elif args.cmd == "stock":
        s = svc.stock_of(args.product_id, args.wh_id)
        print(f"📦 qty_on_hand={s['qty_on_hand']} | qty_reserved={s['qty_reserved']}")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
