import psycopg2
import psycopg2.extras
import psycopg2.sql as sql
import config


def init_db():
    # connect to default 'postgres' database to create the target database if missing
    admin_conn = psycopg2.connect(host=config.DB_HOST, user=config.DB_USER, password=config.DB_PASSWORD, dbname='postgres')
    admin_conn.autocommit = True
    admin_cur = admin_conn.cursor()
    try:
        admin_cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (config.DB_NAME,))
        if not admin_cur.fetchone():
            admin_cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(config.DB_NAME)))
    except Exception:
        pass
    finally:
        admin_cur.close()
        admin_conn.close()

    # connect to the created database and create tables
    conn = psycopg2.connect(host=config.DB_HOST, user=config.DB_USER, password=config.DB_PASSWORD, dbname=config.DB_NAME, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()

    ddls = [
        """
        CREATE TABLE IF NOT EXISTS admin (
            admin_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password TEXT NOT NULL,
            profile_image VARCHAR(255),
            is_approved BOOLEAN DEFAULT FALSE,
            is_super_admin BOOLEAN DEFAULT FALSE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS admin_requests (
            request_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password TEXT NOT NULL,
            status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone VARCHAR(50),
            address TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            category VARCHAR(255),
            price DECIMAL(10,2) NOT NULL,
            image VARCHAR(255),
            quantity INT DEFAULT 0,
            added_by_admin INT,
            FOREIGN KEY (added_by_admin) REFERENCES admin(admin_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            razorpay_order_id VARCHAR(255),
            razorpay_payment_id VARCHAR(255),
            amount DECIMAL(10,2) NOT NULL,
            payment_status VARCHAR(50) DEFAULT 'pending',
            delivery_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS order_items (
            item_id SERIAL PRIMARY KEY,
            order_id INT NOT NULL,
            product_id INT,
            product_name VARCHAR(255) NOT NULL,
            quantity INT NOT NULL,
            price DECIMAL(10,2) NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );
        """,
    ]

    for ddl in ddls:
        try:
            cur.execute(ddl)
        except Exception:
            pass

    for col_sql in [
        "ALTER TABLE admin ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT FALSE",
        "ALTER TABLE admin ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS quantity INT DEFAULT 0",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS added_by_admin INT DEFAULT NULL",
    ]:
        try:
            cur.execute(col_sql)
        except Exception:
            pass

    conn.commit()
    conn.close()
    print("✅ PostgreSQL database initialized successfully!")


if __name__ == '__main__':
    init_db()