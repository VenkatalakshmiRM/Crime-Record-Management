"""Initialize a first-run hosted database, then start the CASEWORK web/API server."""
import api


def ensure_initial_user():
    api.init_db()
    conn = api.connect()
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) AS n FROM users')
        has_users = api.one_dict(cur)['n'] > 0
    finally:
        conn.close()

    if not has_users:
        api.create_user_from_env()


if __name__ == '__main__':
    ensure_initial_user()
    api.main()
