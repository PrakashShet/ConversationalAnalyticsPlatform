"""Seed the sample SQLite database for development."""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "sample.db"

KARNATAKA_CITIES = [
    "Mysore", "Bangalore", "Mangalore", "Hubli", "Belgaum",
    "Shimoga", "Davangere", "Bellary", "Gulbarga", "Udupi",
]
SEGMENTS = ["Consumer", "Corporate", "Home Office"]
CATEGORIES = ["Furniture", "Office Supplies", "Technology"]
PRODUCTS = [
    ("Desk Chair", "Furniture", 4500),
    ("Standing Desk", "Furniture", 12000),
    ("Notebook Pack", "Office Supplies", 350),
    ("Pen Set", "Office Supplies", 180),
    ("Laptop Stand", "Technology", 2800),
    ("USB Hub", "Technology", 950),
    ("Monitor Arm", "Technology", 5200),
    ("Filing Cabinet", "Furniture", 6800),
]
CAMPAIGNS = ["Summer Sale", "Festive Offer", "Clearance", "New Launch", None]
START_DATE = date(2026, 7, 1)
END_DATE = date(2026, 9, 30)


def _random_date(rng: random.Random) -> str:
    delta = (END_DATE - START_DATE).days
    d = START_DATE + timedelta(days=rng.randint(0, delta))
    return d.isoformat()


def seed() -> None:
    rng = random.Random(42)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript("""
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS customers;

        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            segment TEXT NOT NULL
        );

        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL
        );

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            order_date TEXT NOT NULL,
            net_amount REAL NOT NULL,
            qty INTEGER NOT NULL,
            campaign TEXT
        );
    """)

    customers = [
        (i, f"Customer {i:03d}", rng.choice(KARNATAKA_CITIES), rng.choice(SEGMENTS))
        for i in range(1, 51)
    ]
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?)", customers)

    products = [(i, n, c, p) for i, (n, c, p) in enumerate(PRODUCTS, 1)]
    cur.executemany("INSERT INTO products VALUES (?,?,?,?)", products)

    orders = []
    for i in range(1, 301):
        cust_id = rng.randint(1, 50)
        prod_id = rng.randint(1, len(PRODUCTS))
        qty = rng.randint(1, 5)
        price = PRODUCTS[prod_id - 1][2]
        net = round(price * qty * rng.uniform(0.85, 1.0), 2)
        orders.append((
            i, cust_id, prod_id, _random_date(rng), net, qty, rng.choice(CAMPAIGNS),
        ))
    cur.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?)", orders
    )

    conn.commit()
    conn.close()
    print(f"Seeded {DB_PATH} with 50 customers, {len(PRODUCTS)} products, 300 orders")


if __name__ == "__main__":
    seed()
