from pathlib import Path
import csv, gzip, datetime

def snapshot_stocks_to_csv_gz(db, out_dir: str):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    out = Path(out_dir) / f"stocks_{stamp}.csv.gz"
    with db.connect() as conn, gzip.open(out, "wt", newline="", encoding="utf-8") as f:
        cur = conn.cursor()
        cur.execute("""
          SELECT s.product_id, s.warehouse_id, s.qty_on_hand, s.qty_reserved,
                 p.sku, p.name, w.code AS wh_code
          FROM stocks s
          JOIN products p ON p.id=s.product_id
          JOIN warehouses w ON w.id=s.warehouse_id
          ORDER BY p.sku, w.code
        """)
        cols = [d[0] for d in cur.description]
        writer = csv.writer(f)
        writer.writerow(cols)
        for row in cur.fetchall():
            writer.writerow([row[c] for c in cols])
    return str(out)
