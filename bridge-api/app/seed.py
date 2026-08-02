import random
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.models import (
    ApprovalRequest,
    Customer,
    InvoiceDraft,
    Order,
    Pricelist,
    Product,
    Quote,
    User,
)
from app.security import hash_password


def seed_database() -> None:
    db: Session = SessionLocal()
    rng = random.Random(42)
    try:
        admin = db.query(User).filter(User.username == settings.INITIAL_ADMIN_USERNAME).first()
        if not admin:
            db.add(
                User(
                    username=settings.INITIAL_ADMIN_USERNAME,
                    password_hash=hash_password(settings.INITIAL_ADMIN_PASSWORD),
                    role="provider_admin",
                    installation_id=settings.INSTALLATION_ID,
                    must_change_password=settings.is_production_like,
                )
            )
            db.commit()

        if not settings.AUTO_SEED_DEMO_DATA or db.query(Customer).count() > 0:
            return

        pricelists = [
            Pricelist(id="pl-standard", name="Tarifa estándar", discount_percentage=Decimal("0")),
            Pricelist(id="pl-vip", name="Cliente VIP", discount_percentage=Decimal("10")),
            Pricelist(id="pl-wholesale", name="Mayorista", discount_percentage=Decimal("15")),
            Pricelist(id="pl-distributor", name="Distribuidor", discount_percentage=Decimal("20")),
            Pricelist(id="pl-enterprise", name="Empresa", discount_percentage=Decimal("25")),
        ]
        db.add_all(pricelists)
        db.flush()

        customers = []
        for i in range(1, 26):
            customers.append(
                Customer(
                    id=f"cust-{i:03d}",
                    name=f"Cliente Empresa {i}",
                    email=f"contacto{i}@empresa{i}.example",
                    phone=f"+34 600 {i:03d} {i:03d}",
                    company=f"Corporación {i} S.L.",
                    pricelist_id=pricelists[(i - 1) % len(pricelists)].id,
                    tax_exempt=(i == 25),
                )
            )
        db.add_all(customers)
        db.flush()

        categories = ["Industrial", "Electrónica", "Software", "Accesorios", "Suministros"]
        products = []
        for i in range(1, 101):
            category = categories[(i - 1) % len(categories)]
            products.append(
                Product(
                    id=f"prod-{i:03d}",
                    external_id=f"demo-{i:03d}",
                    sku=f"SKU-{category[:3].upper()}-{i:04d}",
                    name=f"Producto {category} Modelo {i}",
                    description=f"Descripción del producto {i} para la categoría {category}.",
                    category=category,
                    attributes={"marca": "Demo", "modelo": str(i)},
                    source="demo",
                    base_price=Decimal(str(round(rng.uniform(10.0, 500.0), 2))),
                    tax_rate=Decimal("0.21"),
                    stock_quantity=rng.randint(20, 200),
                    reserved_stock=0,
                )
            )
        db.add_all(products)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
