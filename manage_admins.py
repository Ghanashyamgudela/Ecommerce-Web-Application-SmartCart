#!/usr/bin/env python3
"""CLI to add or remove super-admin users in the MySQL `admin` table.

Usage examples:
  python manage_admins.py add --email new@admin.com --name "New Admin" --password Secret123
  python manage_admins.py delete --email old@admin.com
"""
import argparse
import getpass
import psycopg2
import psycopg2.extras
import bcrypt
import config


def get_conn():
    conn = psycopg2.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        dbname=config.DB_NAME,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = False
    return conn


def add_super_admin(email, name, password):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT admin_id FROM admin WHERE email=%s", (email,))
        existing = cur.fetchone()
        if existing:
            cur.execute(
                "UPDATE admin SET name=%s, password=%s, is_approved=1, is_super_admin=1 WHERE email=%s",
                (name, hashed, email),
            )
            print(f"Updated existing admin '{email}' → super admin.")
        else:
            cur.execute(
                "INSERT INTO admin (name, email, password, is_approved, is_super_admin) VALUES (%s,%s,%s,1,1)",
                (name, email, hashed),
            )
            print(f"Inserted new super admin '{email}'.")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Error:", e)
    finally:
        cur.close()
        conn.close()


def delete_admin(email):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT admin_id, email FROM admin WHERE email=%s", (email,))
        row = cur.fetchone()
        if not row:
            print(f"No admin found with email: {email}")
            return
        cur.execute("DELETE FROM admin WHERE email=%s", (email,))
        conn.commit()
        print(f"Deleted admin '{email}'.")
    except Exception as e:
        conn.rollback()
        print("Error:", e)
    finally:
        cur.close()
        conn.close()


def main():
    p = argparse.ArgumentParser(description='Manage admin users')
    sub = p.add_subparsers(dest='cmd')

    pa = sub.add_parser('add', help='Add or upgrade a super admin')
    pa.add_argument('--email', required=True)
    pa.add_argument('--name', required=True)
    pa.add_argument('--password', required=False)

    pd = sub.add_parser('delete', help='Delete an admin by email')
    pd.add_argument('--email', required=True)

    args = p.parse_args()
    if args.cmd == 'add':
        pwd = args.password or getpass.getpass('Password for new admin: ')
        add_super_admin(args.email, args.name, pwd)
    elif args.cmd == 'delete':
        confirm = input(f"Are you sure you want to DELETE admin '{args.email}'? type 'yes' to confirm: ")
        if confirm.lower() == 'yes':
            delete_admin(args.email)
        else:
            print('Aborted.')
    else:
        p.print_help()


if __name__ == '__main__':
    main()
