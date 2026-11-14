"""Seed DynamoDB (customers + orders) and upload policy documents to S3.

Usage:  python infrastructure/seed_data.py

Order dates are generated relative to *today* so the return-window scenarios
(30 days Standard / 60 days Premium) always behave the same way no matter when
you run the project. Re-running the script resets the data.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import boto3  # noqa: E402

import config  # noqa: E402

POLICY_DIR = Path(__file__).resolve().parent / "policies"
TODAY = datetime.now(timezone.utc).date()


def days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


CUSTOMERS = [
    {"customer_id": "CUST-001", "name": "Alice Johnson", "email": "alice.johnson@example.com",
     "tier": "Standard", "member_since": "2023-04-12"},
    {"customer_id": "CUST-002", "name": "Brian Lee", "email": "brian.lee@example.com",
     "tier": "Premium", "member_since": "2021-09-03"},
    {"customer_id": "CUST-003", "name": "Carmen Diaz", "email": "carmen.diaz@example.com",
     "tier": "Standard", "member_since": "2024-01-20"},
    {"customer_id": "CUST-004", "name": "David Okafor", "email": "david.okafor@example.com",
     "tier": "Premium", "member_since": "2022-06-15"},
    {"customer_id": "CUST-005", "name": "Emma Schultz", "email": "emma.schultz@example.com",
     "tier": "Standard", "member_since": "2025-02-28"},
]

# (customer, order, product, category, price, qty, status, placed_days_ago, delivered_days_ago)
ORDERS = [
    # Scenario 1 - Standard customer, delivered 12 days ago -> eligible (30-day window)
    ("CUST-001", "ORD-27176", "Wireless Noise-Cancelling Headphones", "Electronics", "149.99", 1, "Delivered", 16, 12),
    ("CUST-001", "ORD-27190", "Stainless Steel Water Bottle", "Home", "24.99", 2, "Shipped", 2, None),
    ("CUST-001", "ORD-26011", "Running Shoes", "Apparel", "89.99", 1, "Delivered", 50, 45),
    # Premium customer, delivered 45 days ago -> eligible only because Premium (60 days)
    ("CUST-002", "ORD-31002", "4K Streaming Media Player", "Electronics", "59.99", 1, "Delivered", 49, 45),
    ("CUST-002", "ORD-31045", "Ergonomic Office Chair", "Furniture", "329.00", 1, "Processing", 1, None),
    # Standard customer, delivered 45 days ago -> NOT eligible
    ("CUST-003", "ORD-40517", "Smart Fitness Watch", "Electronics", "199.99", 1, "Delivered", 50, 45),
    # Premium customer, delivered 75 days ago -> NOT eligible even for Premium
    ("CUST-004", "ORD-52210", "Robot Vacuum Cleaner", "Home", "279.99", 1, "Delivered", 80, 75),
    ("CUST-004", "ORD-52288", "Bluetooth Speaker", "Electronics", "79.99", 1, "Delivered", 10, 7),
    ("CUST-005", "ORD-60001", "Yoga Mat", "Fitness", "34.99", 1, "Delivered", 6, 3),
]


def seed_dynamodb() -> None:
    ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
    customers = ddb.Table(config.CUSTOMERS_TABLE)
    orders = ddb.Table(config.ORDERS_TABLE)

    with customers.batch_writer() as batch:
        for c in CUSTOMERS:
            batch.put_item(Item=c)
    print(f"  ✓ {len(CUSTOMERS)} customers -> {config.CUSTOMERS_TABLE}")

    with orders.batch_writer() as batch:
        for cust, oid, product, cat, price, qty, status, placed, delivered in ORDERS:
            item = {
                "customer_id": cust,
                "order_id": oid,
                "product_name": product,
                "category": cat,
                "unit_price": Decimal(price),
                "quantity": qty,
                "total": Decimal(price) * qty,
                "status": status,
                "order_date": days_ago(placed),
            }
            if delivered is not None:
                item["delivery_date"] = days_ago(delivered)
            batch.put_item(Item=item)
    print(f"  ✓ {len(ORDERS)} orders    -> {config.ORDERS_TABLE}")


def upload_policies() -> None:
    if not config.POLICY_BUCKET:
        raise SystemExit("Policy bucket not found - deploy infrastructure/starter_stack.yaml first.")
    s3 = boto3.client("s3", region_name=config.AWS_REGION)
    count = 0
    for path in sorted(POLICY_DIR.rglob("*.md")):
        key = f"policies/{path.relative_to(POLICY_DIR).as_posix()}"
        s3.upload_file(str(path), config.POLICY_BUCKET, key, ExtraArgs={"ContentType": "text/markdown"})
        print(f"  ✓ s3://{config.POLICY_BUCKET}/{key}")
        count += 1
    print(f"  ✓ {count} policy documents uploaded")


if __name__ == "__main__":
    print(f"Seeding NovaMart data in {config.AWS_REGION} (today = {TODAY})")
    seed_dynamodb()
    upload_policies()
    print("Done.")
