from infra.db_interface import DB
from utils.security import hash_password, verify_password
from utils.exceptions import NotFound

class AuthService:
    def __init__(self, db: DB):
        self.db = db

    def ensure_default_admin(self):
        # 确保至少有一个 admin 账号（admin/admin123），首次创建；若已存在则不改密码
        with self.db.transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE username=?", ("admin",))
            row = cur.fetchone()
            if row:
                return
            pw = hash_password("admin123")
            cur.execute("INSERT INTO users (username, password_hash, is_active) VALUES (?,?,1)",
                        ("admin", pw))
            user_id = cur.lastrowid
            # 绑定 admin 角色
            cur.execute("SELECT id FROM roles WHERE code='admin'")
            role = cur.fetchone()
            if role:
                cur.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)",
                            (user_id, role["id"]))

    def register_user(self, username: str, password: str, role_codes: list[str] | None=None) -> int:
        with self.db.transaction() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password_hash, is_active) VALUES (?,?,1)",
                        (username, hash_password(password)))
            uid = cur.lastrowid
            if role_codes:
                for code in role_codes:
                    cur.execute("SELECT id FROM roles WHERE code=?", (code,))
                    r = cur.fetchone()
                    if r:
                        cur.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)",
                                    (uid, r["id"]))
            return uid

    def authenticate(self, username: str, password: str) -> dict | None:
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,))
            u = cur.fetchone()
            if not u:
                return None
            if not verify_password(password, u["password_hash"]):
                return None
            # 拉角色
            cur.execute("""
                SELECT roles.code FROM roles
                JOIN user_roles ur ON ur.role_id=roles.id
                WHERE ur.user_id=?
            """, (u["id"],))
            roles = [r["code"] for r in cur.fetchall()]
            return {"id": u["id"], "username": u["username"], "roles": roles}

    def has_role(self, user_id: int, role_code: str) -> bool:
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 1 FROM user_roles ur
                JOIN roles r ON r.id=ur.role_id
                WHERE ur.user_id=? AND r.code=?
            """, (user_id, role_code))
            return cur.fetchone() is not None

    def set_active(self, user_id: int, active: bool):
        with self.db.transaction() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id))
            if cur.rowcount == 0:
                raise NotFound("用户不存在")
