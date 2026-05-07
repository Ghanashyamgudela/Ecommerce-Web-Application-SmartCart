-- Converted PostgreSQL dump (simplified)

DROP TABLE IF EXISTS admin CASCADE;
CREATE TABLE admin (
  admin_id SERIAL PRIMARY KEY,
  name varchar(255) NOT NULL,
  email varchar(255) NOT NULL UNIQUE,
  password text NOT NULL,
  profile_image varchar(255),
  is_approved boolean DEFAULT FALSE,
  is_super_admin boolean DEFAULT FALSE
);

DROP TABLE IF EXISTS admin_requests CASCADE;
CREATE TABLE admin_requests (
  request_id SERIAL PRIMARY KEY,
  name varchar(255) NOT NULL,
  email varchar(255) NOT NULL UNIQUE,
  password text NOT NULL,
  status varchar(50) DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS users CASCADE;
CREATE TABLE users (
  user_id SERIAL PRIMARY KEY,
  name varchar(255) NOT NULL,
  email varchar(255) NOT NULL UNIQUE,
  password text NOT NULL,
  phone varchar(50),
  address text
);

DROP TABLE IF EXISTS products CASCADE;
CREATE TABLE products (
  product_id SERIAL PRIMARY KEY,
  name varchar(255) NOT NULL,
  description text,
  category varchar(255),
  price numeric(10,2) NOT NULL,
  image varchar(255),
  quantity int DEFAULT 0,
  added_by_admin int REFERENCES admin(admin_id)
);

DROP TABLE IF EXISTS orders CASCADE;
CREATE TABLE orders (
  order_id SERIAL PRIMARY KEY,
  user_id int NOT NULL REFERENCES users(user_id),
  razorpay_order_id varchar(255),
  razorpay_payment_id varchar(255),
  amount numeric(10,2) NOT NULL,
  payment_status varchar(50) DEFAULT 'pending',
  delivery_address text,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS order_items CASCADE;
CREATE TABLE order_items (
  item_id SERIAL PRIMARY KEY,
  order_id int NOT NULL REFERENCES orders(order_id),
  product_id int REFERENCES products(product_id),
  product_name varchar(255) NOT NULL,
  quantity int NOT NULL,
  price numeric(10,2) NOT NULL
);

-- Sample data inserts (converted from original MySQL dump)
INSERT INTO admin (admin_id, name, email, password, profile_image, is_approved, is_super_admin) VALUES
(3,'New Admin','new@admin.com','$2b$12$B3OzT8WjVa3COfnoOvcHN.dANUU1J3NoCrBdX4OhRTu/na7nKcvEG',NULL,TRUE,TRUE),
(4,'Ghana','ghana19183@gmail.com','$2b$12$vDLoR7bxOb1NU541fmtvxuG9Utq5.D8EEvQv.BBmLNPkJoapLSen.','14947fbff70e4abc847fed230fe004f8_jpeg',TRUE,TRUE);

INSERT INTO admin_requests (request_id, name, email, password, status, created_at) VALUES
(1,'Ghana Shyam Gudela','ghana19183@gmail.com','$2b$12$4uFIQp3LxRE.9j0nNDXY/eo3z29EasqqFHyNOce/S17pJPHXes92O','rejected','2026-05-04 15:37:55'),
(2,'admin','saciha5944@inraud.com','$2b$12$jL8Q81cdG0vRc.X6iR9muuRVg9u9M/WiPSqLUB5JARiToqh1x4D9G','rejected','2026-05-06 23:53:12');

INSERT INTO users (user_id, name, email, password, phone, address) VALUES
(2,'Madhu','nomil16455@kynninc.com','$2b$12$OKmEO3syC6gpzJe3l4HESeoGoY6CHzLwhQLSFwwtF58ARqxfeYvtS','',''),
(3,'Ghana Shyam Gudela','ghanagudela@gmail.com','$2b$12$QPMljTrw5TtiSZctXzzeQeCfM3FQMKP8tOMimWA9wnTYo.OxYwxBO','09492223244','ddkkcnkd');

-- Note: This is a simplified conversion. For very large INSERTs (e.g., products), consider using COPY or splitting inserts.
