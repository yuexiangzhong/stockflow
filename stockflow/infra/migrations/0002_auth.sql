-- 认证&权限基础表
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS roles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,           -- 'admin','operator','viewer'
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_id INTEGER NOT NULL,
  role_id INTEGER NOT NULL,
  PRIMARY KEY (user_id, role_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
);

-- 会话吊销（可选）
CREATE TABLE IF NOT EXISTS revoked_tokens (
  jti TEXT PRIMARY KEY,
  revoked_at TEXT DEFAULT (datetime('now'))
);

-- 初始化基础角色（存在则忽略）
INSERT OR IGNORE INTO roles (id, code, name) VALUES
  (1, 'admin', '管理员'),
  (2, 'operator', '操作员'),
  (3, 'viewer', '只读');

-- 如果没有任何用户，创建一个默认管理员（用户名: admin / 密码: admin123；启动时会自动重设哈希）
