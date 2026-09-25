"""
Seed data: default user + bilingual chart of accounts.

Business expense categories map to real Form 1040 Schedule C lines so the
year-end export is something a tax preparer can actually use.
User-facing names are plain language in both English and Spanish —
no accounting vocabulary on the surface.
"""
from sqlalchemy.orm import Session

from .models import Account, AccountType, User

# (code, name_en, name_es, type, is_business, schedule_c_line)
DEFAULT_ACCOUNTS = [
    # ---- Core (hidden plumbing; the user never picks these directly) ----
    ("1000", "Cash & bank", "Efectivo y banco", AccountType.asset, False, None),
    ("3000", "Owner", "Dueño", AccountType.equity, False, None),

    # ---- Money in ----
    ("4000", "Work income", "Ingresos del trabajo", AccountType.income, True, None),
    ("4100", "Other income", "Otros ingresos", AccountType.income, False, None),

    # ---- Business money out (Schedule C mapped) ----
    ("5008", "Advertising", "Publicidad", AccountType.expense, True, "8"),
    ("5009", "Car & truck", "Carro y camioneta", AccountType.expense, True, "9"),
    ("5010", "Commissions & fees", "Comisiones y cuotas", AccountType.expense, True, "10"),
    ("5011", "Contract labor", "Trabajadores por contrato", AccountType.expense, True, "11"),
    ("5015", "Insurance", "Seguro", AccountType.expense, True, "15"),
    ("5017", "Legal & professional", "Servicios legales y profesionales", AccountType.expense, True, "17"),
    ("5018", "Office expense", "Gastos de oficina", AccountType.expense, True, "18"),
    ("5020", "Rent (business)", "Renta (negocio)", AccountType.expense, True, "20b"),
    ("5021", "Repairs & maintenance", "Reparaciones y mantenimiento", AccountType.expense, True, "21"),
    ("5022", "Supplies & materials", "Materiales", AccountType.expense, True, "22"),
    ("5023", "Taxes & licenses", "Impuestos y licencias", AccountType.expense, True, "23"),
    ("5024", "Travel", "Viajes", AccountType.expense, True, "24a"),
    ("5025", "Meals (business)", "Comidas (negocio)", AccountType.expense, True, "24b"),
    ("5026", "Utilities & phone", "Luz, agua y teléfono (negocio)", AccountType.expense, True, "25"),
    ("5027", "Other business expense", "Otros gastos del negocio", AccountType.expense, True, "27a"),

    # ---- Personal money out ----
    ("6000", "Rent / housing", "Renta / vivienda", AccountType.expense, False, None),
    ("6010", "Groceries & food", "Comida y despensa", AccountType.expense, False, None),
    ("6020", "Transport", "Transporte", AccountType.expense, False, None),
    ("6030", "Health", "Salud", AccountType.expense, False, None),
    ("6040", "Family support / remittances", "Apoyo familiar / remesas", AccountType.expense, False, None),
    ("6050", "Kids & school", "Hijos y escuela", AccountType.expense, False, None),
    ("6090", "Other personal", "Otros gastos personales", AccountType.expense, False, None),
]


def seed(db: Session) -> User:
    user = db.query(User).first()
    if user is None:
        user = User(name="Default", locale="es", mode="both")
        db.add(user)
        db.flush()
    existing = {a.code for a in db.query(Account).filter_by(user_id=user.id)}
    for code, en, es, typ, biz, line in DEFAULT_ACCOUNTS:
        if code not in existing:
            db.add(Account(
                user_id=user.id, code=code, name_en=en, name_es=es,
                type=typ, is_business=biz, schedule_c_line=line,
            ))
    db.commit()
    return user
